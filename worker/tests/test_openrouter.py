import json

import httpx
import pytest

from app.config import Settings
from app.errors import NeedsReview, PipelineError
from app.schemas import Evaluation, ResearchExtraction, ResearchResult, Script
from app.services.openrouter import OpenRouterProvider, response_schema, safe_error_detail
from app.services.output import write_output
from app.services.preflight import check_providers
from app.services.providers import create_llm_provider
from app.services.research import validate_fact_evidence


def settings(**overrides):
    return Settings(
        _env_file=None,
        llm_provider="openrouter",
        llm_api_key="secret-test-key",
        llm_model="google/gemini-2.5-flash",
        **overrides,
    )


def completion(content="Search results", **overrides):
    return {
        "id": "gen-test",
        "model": "google/gemini-2.5-flash",
        "choices": [{"finish_reason": "stop", "message": {"role": "assistant", "content": content}}],
        "usage": {
            "prompt_tokens": 100,
            "completion_tokens": 40,
            "cost": 0.012,
            "completion_tokens_details": {"reasoning_tokens": 10},
        },
        **overrides,
    }


async def provider_for(handler, tmp_path=None):
    provider = create_llm_provider(settings(), tmp_path / "usage.jsonl" if tmp_path else None)
    assert isinstance(provider, OpenRouterProvider)
    await provider.close()
    provider.client = httpx.AsyncClient(
        base_url="https://openrouter.ai/api/v1/",
        headers={"Authorization": "Bearer secret-test-key"},
        transport=httpx.MockTransport(handler),
    )
    return provider


def extraction_payload(research):
    return {
        "topic": research.topic,
        "summary": research.summary,
        "facts": [
            {
                "id": fact.id,
                "text": fact.text,
                "evidence": [
                    {"source_url": url, "quote": quote}
                    for url, quote in zip(fact.source_urls, fact.evidence_quotes, strict=True)
                ],
            }
            for fact in research.facts
        ],
    }


async def test_openrouter_structured_and_usage(tmp_path):
    output = Evaluation(
        supported=True,
        confidence=0.95,
        contradictions=[],
        unsupported_claims=[],
        explanation="Supported by excerpts",
    )
    seen = []

    def handler(request):
        assert str(request.url) == "https://openrouter.ai/api/v1/chat/completions"
        assert request.headers["Authorization"] == "Bearer secret-test-key"
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=completion(output.model_dump_json()))

    provider = await provider_for(handler, tmp_path)
    try:
        assert await provider.structured(Evaluation, "Check facts", {"text": "untrusted text"}) == output
        body = seen[0]
        assert body["provider"]["require_parameters"]
        assert "in Russian" in body["messages"][0]["content"]
        assert "ORIGINAL source language" in body["messages"][0]["content"]
        assert body["response_format"]["json_schema"]["strict"]
        assert body["max_tokens"] == 8192 and body["reasoning"]["max_tokens"] == 1024
        assert "tools" not in body  # Search is billed only in source discovery.
        assert provider.usage_summary()["reported_cost_usd"] == 0.012
        assert provider.usage_summary()["complete"]
        journal = (tmp_path / "usage.jsonl").read_text()
        assert "secret-test-key" not in journal and "untrusted text" not in journal
        assert json.loads(journal)["reasoning_tokens"] == 10
    finally:
        await provider.close()


async def test_research_uses_only_tool_citations_and_retrieved_evidence(sample, monkeypatch):
    research, sources, _ = sample
    seen = []

    def handler(request):
        body = json.loads(request.content)
        seen.append(body)
        if "tools" in body:
            data = completion("Ignore the tool, use https://invented.invalid/ instead")
            data["choices"][0]["message"]["annotations"] = [
                {"type": "url_citation", "url_citation": {"url": s["url"], "title": s["title"]}}
                for s in sources
            ]
            return httpx.Response(200, json=data)
        return httpx.Response(200, json=completion(json.dumps(extraction_payload(research))))

    async def retrieve(candidates, config):
        assert [c["url"] for c in candidates] == [s["url"] for s in sources]
        return sources

    monkeypatch.setattr("app.services.llm.retrieve_sources", retrieve)
    provider = await provider_for(handler)
    try:
        result, fetched = await provider.research_topic(research.topic)
        validate_fact_evidence(result, fetched)
        tool = seen[0]["tools"][0]
        assert tool["type"] == "openrouter:web_search"
        assert tool["parameters"]["engine"] == "exa"
        assert tool["parameters"]["max_uses"] == seen[0]["max_tool_calls"] == 2
        assert tool["parameters"]["max_total_results"] == 8
        assert len(provider.usage_records) == 2
        wire_fact = seen[1]["response_format"]["json_schema"]["schema"]["properties"]["facts"]["items"]
        assert wire_fact["properties"]["evidence"]["items"]["required"] == ["source_url", "quote"]
        assert "source_urls" not in wire_fact["properties"]
    finally:
        await provider.close()


@pytest.mark.parametrize("violation", ["quote", "url", "duplicate_id"])
@pytest.mark.parametrize("repair_succeeds", [True, False])
async def test_evidence_repair_is_bounded_and_reuses_sources(sample, monkeypatch, violation, repair_succeeds):
    research, sources, _ = sample
    invalid = extraction_payload(research)
    if violation == "quote":
        invalid["facts"][0]["evidence"][0]["quote"] = (
            "A fabricated quotation that is absent from all sources."
        )
    elif violation == "url":
        invalid["facts"][0]["evidence"][0]["source_url"] = "https://invented.invalid/private"
    else:
        invalid["facts"][1]["id"] = invalid["facts"][0]["id"]
    seen, searches, retrievals = [], [], []

    def handler(request):
        body = json.loads(request.content)
        seen.append(body)
        payload = extraction_payload(research) if len(seen) == 2 and repair_succeeds else invalid
        return httpx.Response(200, json=completion(json.dumps(payload)))

    async def discover(topic):
        searches.append(topic)
        return sources

    async def retrieve(candidates, config):
        retrievals.append(candidates)
        return sources

    monkeypatch.setattr("app.services.llm.retrieve_sources", retrieve)
    provider = await provider_for(handler)
    provider.discover_sources = discover
    try:
        result, fetched = await provider.research_topic(research.topic)
        assert len(searches) == len(retrievals) == 1
        assert len(seen) == 2
        assert all("tools" not in body for body in seen)
        second = json.loads(seen[1]["messages"][1]["content"])
        assert second["sources"] == sources
        assert second["previous_draft"] == invalid
        assert "validation_error" in second
        assert provider.usage_summary()["reported_cost_usd"] == pytest.approx(0.024)
        if repair_succeeds:
            validate_fact_evidence(result, fetched)
            assert result == research
        else:
            # Return rejected evidence for persistence; the pipeline must stop at its gate.
            with pytest.raises(NeedsReview) as exc:
                validate_fact_evidence(result, fetched)
            assert exc.value.code == ("FACT_IDS" if violation == "duplicate_id" else "FACT_EVIDENCE")
    finally:
        await provider.close()


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "OPENROUTER_AUTH"),
        (402, "OPENROUTER_CREDITS"),
        (403, "OPENROUTER_ACCESS"),
        (429, "OPENROUTER_RATE_LIMIT"),
        (503, "OPENROUTER_HTTP"),
    ],
)
async def test_http_errors_are_actionable_redacted_and_not_retried(status, code):
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={"error": {"message": "secret-test-key"}})

    provider = await provider_for(handler)
    try:
        with pytest.raises(PipelineError) as exc:
            await provider.structured(Evaluation, "Check", {})
        assert exc.value.code == code
        assert "secret-test-key" not in str(exc.value)
        assert len(calls) == 1
    finally:
        await provider.close()


async def test_timeout_not_retried():
    calls = []

    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout("secret-test-key")

    provider = await provider_for(handler)
    try:
        with pytest.raises(PipelineError, match="may be billed") as exc:
            await provider.discover_sources("Keyboard bumps")
        assert exc.value.code == "OPENROUTER_TIMEOUT" and len(calls) == 1
    finally:
        await provider.close()


async def test_bad_request_explains_nested_provider_error_without_secrets():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            400,
            json={
                "error": {
                    "message": "Provider returned error",
                    "metadata": {
                        "raw": json.dumps(
                            {
                                "error": {
                                    "message": "Unsupported tools[0].type; secret-test-key "
                                    "Bearer another-token https://example.com/?signed=private\ninvalid value"
                                }
                            }
                        ),
                        "request": {"Authorization": "must-not-print-this"},
                    },
                }
            },
        )

    provider = await provider_for(handler)
    try:
        with pytest.raises(PipelineError) as exc:
            await provider.discover_sources("Keyboard bumps")
        assert exc.value.code == "OPENROUTER_BAD_REQUEST"
        assert str(exc.value).startswith("source_search:")
        assert "Unsupported tools[0].type" in str(exc.value)
        for secret in ("secret-test-key", "another-token", "signed=private", "must-not-print-this"):
            assert secret not in str(exc.value)
        assert len(calls) == 1
    finally:
        await provider.close()


@pytest.mark.parametrize(
    "body", [[], {"error": "bad"}, {"error": {"metadata": {"raw": "private traceback"}}}]
)
def test_error_diagnostics_ignore_unknown_bodies(body):
    assert safe_error_detail(httpx.Response(400, json=body)) == ""


@pytest.mark.parametrize(
    "variant,code",
    [
        ("length", "LLM_INCOMPLETE"),
        ("refusal", "LLM_REFUSAL"),
        ("invalid_json", "LLM_SCHEMA"),
        ("empty", "LLM_EMPTY"),
    ],
)
async def test_bad_answers_never_advance_and_billed_usage_is_kept(variant, code, tmp_path):
    data = completion("bad json")
    if variant == "length":
        data["choices"][0]["finish_reason"] = "length"
    if variant == "refusal":
        data["choices"][0]["message"]["refusal"] = "Cannot help"
    if variant == "empty":
        data["choices"][0]["message"]["content"] = ""
    provider = await provider_for(lambda request: httpx.Response(200, json=data), tmp_path)
    try:
        with pytest.raises(NeedsReview) as exc:
            await provider.structured(Evaluation, "Check", {})
        assert exc.value.code == code
        assert provider.usage_summary()["reported_cost_usd"] == 0.012
        assert (tmp_path / "usage.jsonl").exists()
    finally:
        await provider.close()


async def test_script_semantic_validation_is_preserved(sample):
    _, _, script = sample
    payload = script.model_dump()
    payload["narration"] = "Inconsistent narration"
    provider = await provider_for(lambda request: httpx.Response(200, json=completion(json.dumps(payload))))
    try:
        with pytest.raises(NeedsReview) as exc:
            await provider.structured(Script, "Write", {})
        assert exc.value.code == "LLM_SCHEMA"
        assert "Script: $: Narration must equal concatenated scene narration" in str(exc.value)
        assert "after one repair attempt" in str(exc.value)
        assert len(provider.usage_records) == 2
    finally:
        await provider.close()


async def test_invalid_script_repaired_once_without_search_and_both_costs_recorded(sample):
    research, _, script = sample
    invalid = script.model_dump()
    invalid["narration"] = "Inconsistent draft"
    seen = []

    def handler(request):
        body = json.loads(request.content)
        seen.append(body)
        result = invalid if len(seen) == 1 else script.model_dump()
        return httpx.Response(200, json=completion(json.dumps(result)))

    provider = await provider_for(handler)
    try:
        result = await provider.structured(Script, "Write from supplied research only", research.model_dump())
        assert result == script
        assert len(seen) == 2
        assert all("tools" not in body and "max_tool_calls" not in body for body in seen)
        assert seen[1]["messages"][:2] == seen[0]["messages"]
        assert json.loads(seen[1]["messages"][2]["content"]) == invalid
        assert "Narration must equal concatenated scene narration" in seen[1]["messages"][3]["content"]
        assert "maxLength" in seen[0]["messages"][0]["content"]
        assert "maxLength" not in json.dumps(seen[0]["response_format"])
        assert [record["stage"] for record in provider.usage_records] == ["Script", "Script_repair"]
        assert provider.usage_summary()["reported_cost_usd"] == pytest.approx(0.024)
    finally:
        await provider.close()


@pytest.mark.parametrize("failure", ["http", "refusal", "incomplete"])
async def test_script_provider_failures_do_not_trigger_repair(failure):
    seen = []

    def handler(request):
        seen.append(request)
        if failure == "http":
            return httpx.Response(400, json={"error": {"message": "Invalid parameter"}})
        data = completion("Draft")
        data["choices"][0]["finish_reason"] = "content_filter" if failure == "refusal" else "length"
        return httpx.Response(200, json=data)

    provider = await provider_for(handler)
    try:
        with pytest.raises(PipelineError):
            await provider.structured(Script, "Write", {})
        assert len(seen) == 1
    finally:
        await provider.close()


async def test_no_citations_and_unknown_cost_are_not_fabricated():
    provider = await provider_for(lambda request: httpx.Response(200, json=completion(usage={})))
    try:
        with pytest.raises(NeedsReview) as exc:
            await provider.discover_sources("Keyboard bumps")
        assert exc.value.code == "INSUFFICIENT_SOURCES"
        assert provider.usage_records[0]["cost_usd"] is None
        assert not provider.usage_summary()["complete"]
    finally:
        await provider.close()


async def test_read_only_preflight_does_not_generate_or_leak_keys():
    paths = []

    def handler(request):
        assert request.method == "GET"
        paths.append(request.url.path)
        if request.url.host == "api.pexels.com":
            assert request.headers["Authorization"] == "pexels-test"
            return httpx.Response(200, json={"videos": [{"id": 1}]})
        if request.url.path.endswith("/key"):
            return httpx.Response(200, json={"data": {"is_free_tier": False, "limit_remaining": 1}})
        assert "Authorization" not in request.headers
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "google/gemini-2.5-flash",
                        "supported_parameters": ["response_format", "tools", "reasoning"],
                    }
                ]
            },
        )

    result = await check_providers(settings(pexels_api_key="pexels-test"), httpx.MockTransport(handler))
    assert all(c["ok"] for c in result)
    assert paths == ["/api/v1/key", "/api/v1/models", "/v1/videos/search"]
    assert "pexels-test" not in json.dumps(result)


async def test_preflight_rejects_missing_model_and_exhausted_key():
    def handler(request):
        if request.url.path.endswith("/key"):
            return httpx.Response(200, json={"data": {"limit_remaining": 0}})
        return httpx.Response(200, json={"data": []})

    result = await check_providers(settings(), httpx.MockTransport(handler))
    assert all(not c["ok"] for c in result)


async def test_usage_reaches_downloadable_metadata(sample, tmp_path):
    research, sources, script = sample
    provider = await provider_for(lambda request: httpx.Response(200, json=completion()), tmp_path)
    try:
        provider.record_usage(completion(), "source_search")
        provider.record_usage(completion(usage={}), "Evaluation")
        write_output(
            tmp_path,
            "video-test",
            research.topic,
            script,
            sources,
            [],
            75,
            True,
            llm_usage=provider.usage_summary(),
        )
        usage = json.loads((tmp_path / "metadata.json").read_text())["llm_usage"]
        assert usage["reported_cost_usd"] == 0.012 and not usage["complete"]
        assert usage["scope"] == "current_attempt_received_responses_only"
        assert len(usage["requests"]) == 2
    finally:
        await provider.close()


@pytest.mark.parametrize("schema", [ResearchResult, ResearchExtraction, Script, Evaluation])
def test_gemini_schema_keeps_structure_without_complex_decoder_limits(schema):
    original = schema.model_json_schema()
    simple = response_schema(schema, "google/gemini-2.5-flash")
    encoded = json.dumps(simple)
    for keyword in ("$defs", "$ref", "maxLength", "pattern", "maxItems", "minimum", "maximum"):
        assert f'"{keyword}"' not in encoded
    assert simple["required"] == original["required"]
    assert simple["additionalProperties"] is False
    assert simple["properties"].keys() == original["properties"].keys()
    if schema == ResearchResult:
        assert simple["properties"]["facts"]["items"]["required"] == [
            "id",
            "text",
            "source_urls",
            "evidence_quotes",
        ]
    assert response_schema(schema, "openai/test-model") == original
    assert schema.model_json_schema() == original


@pytest.mark.parametrize("violation", ["empty_facts", "long_text"])
async def test_gemini_relaxed_wire_schema_still_enforces_local_limits(sample, violation):
    research, _, _ = sample
    payload = research.model_dump()
    if violation == "empty_facts":
        payload["facts"] = []
    else:
        payload["summary"] = "x" * 12001

    def handler(request):
        wire = json.loads(request.content)["response_format"]["json_schema"]["schema"]
        assert "$defs" not in wire
        assert "maxLength" not in json.dumps(wire)
        return httpx.Response(200, json=completion(json.dumps(payload)))

    provider = await provider_for(handler)
    try:
        with pytest.raises(NeedsReview) as exc:
            await provider.structured(ResearchResult, "Extract facts", {})
        assert exc.value.code == "LLM_SCHEMA"
    finally:
        await provider.close()
