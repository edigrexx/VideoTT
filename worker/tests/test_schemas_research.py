import pytest
from pydantic import ValidationError

from app.config import Settings
from app.errors import NeedsReview
from app.schemas import Evaluation, ResearchExtraction, Script, VideoCreate
from app.services.research import validate_fact_evidence, validate_script_evidence


def test_script_roundtrip(sample):
    script = sample[2]
    assert Script.model_validate_json(script.model_dump_json()) == script


@pytest.mark.parametrize("mutation", ["empty", "narration", "order", "hashtags", "hook"])
def test_script_rejects_bad_structure(sample, mutation):
    data = sample[2].model_dump()
    if mutation == "empty":
        data["scenes"] = []
    elif mutation == "narration":
        data["narration"] += " Invented additional fact."
    elif mutation == "order":
        data["scenes"][0]["order"] = 2
    elif mutation == "hashtags":
        data["hashtags"] = ["#bad", "test", "test2"]
    else:
        data["hook"] = "This is not the actual opening"
    with pytest.raises(ValidationError):
        Script.model_validate(data)


def test_quotes_must_exist_in_retrieved_text(sample):
    research, sources, _ = sample
    validate_fact_evidence(research, sources)
    research.facts[0].evidence_quotes = ["This is a fabricated quotation that is absent from the source."]
    with pytest.raises(NeedsReview, match="missing"):
        validate_fact_evidence(research, sources)


def test_research_extraction_pairs_sources_and_quotes(sample):
    research, sources, _ = sample
    data = {
        "topic": research.topic,
        "summary": research.summary,
        "facts": [
            {
                "id": "f1",
                "text": "First fact",
                "evidence": [
                    {"source_url": sources[0]["url"], "quote": "First source passage"},
                    {"source_url": "fixture://second-source", "quote": "Second source passage"},
                ],
            },
            {
                "id": "f2",
                "text": "Second fact",
                "evidence": [
                    {"source_url": sources[0]["url"], "quote": "Another source passage"},
                ],
            },
        ],
    }
    converted = ResearchExtraction.model_validate(data).to_research()
    assert converted.facts[0].source_urls == [sources[0]["url"], "fixture://second-source"]
    assert converted.facts[0].evidence_quotes == ["First source passage", "Second source passage"]
    assert all(len(fact.source_urls) == len(fact.evidence_quotes) for fact in converted.facts)
    del data["facts"][0]["evidence"][1]["quote"]
    with pytest.raises(ValidationError):
        ResearchExtraction.model_validate(data)


def test_evidence_mismatch_diagnostics_include_counts_without_source_text(sample):
    research, sources, _ = sample
    research.facts[0].source_urls = ["private-source-a", "private-source-b"]
    research.facts[0].evidence_quotes = ["private-quote"]
    with pytest.raises(NeedsReview) as exc:
        validate_fact_evidence(research, sources)
    assert "facts[0]: 2 source URLs but 1 quotes" in str(exc.value)
    assert "private" not in str(exc.value)


def test_fact_urls_must_have_been_fetched(sample):
    research, sources, _ = sample
    research.facts[0].source_urls = ["https://invented.example/page"]
    with pytest.raises(NeedsReview):
        validate_fact_evidence(research, sources)


def test_script_fact_gate(sample):
    research, sources, script = sample
    evaluation = Evaluation(
        supported=True, confidence=0.95, contradictions=[], unsupported_claims=[], explanation="test"
    )
    validate_script_evidence(script, research, evaluation, 0.85)
    evaluation.unsupported_claims = ["Unsupported origin story"]
    with pytest.raises(NeedsReview):
        validate_script_evidence(script, research, evaluation, 0.85)
    evaluation.unsupported_claims = []
    script.scenes[0].fact_ids = ["made_up"]
    with pytest.raises(NeedsReview):
        validate_script_evidence(script, research, evaluation, 0.85)


def test_mock_never_accidentally_used_as_production():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, llm_provider="mock")
    with pytest.raises(ValidationError):
        Settings(_env_file=None, llm_provider="mock", allow_test_mode=True)
    with pytest.raises(ValidationError):
        VideoCreate(topic="Some topic", topic_id="cf09aec1-c6c7-4a17-aa2c-c8c8f253e541")
