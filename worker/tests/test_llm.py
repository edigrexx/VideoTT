import json

import httpx2
import pytest
from openai import AsyncOpenAI

from app.config import Settings
from app.errors import NeedsReview
from app.schemas import Evaluation
from app.services.llm import OpenAIProvider


async def test_openai_structured_request_and_parsing():
    seen = []
    output = Evaluation(
        supported=True,
        confidence=0.95,
        contradictions=[],
        unsupported_claims=[],
        explanation="Supported by supplied excerpts",
    )

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx2.Response(
            200,
            json={
                "id": "resp_test",
                "object": "response",
                "created_at": 1,
                "status": "completed",
                "model": "test-model-from-env",
                "output": [
                    {
                        "id": "msg_test",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [
                            {"type": "output_text", "text": output.model_dump_json(), "annotations": []}
                        ],
                    }
                ],
            },
        )

    provider = OpenAIProvider(
        Settings(_env_file=None, llm_api_key="test-key", llm_model="test-model-from-env")
    )
    await provider.client.close()
    provider.client = AsyncOpenAI(
        api_key="test-key", http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    )
    try:
        result = await provider.structured(Evaluation, "Evaluate supplied evidence only.", {"text": "test"})
        assert result == output
        assert seen[0]["model"] == "test-model-from-env"
        assert seen[0]["text"]["format"]["type"] == "json_schema"
        assert seen[0]["text"]["format"]["strict"] is True
        assert seen[0]["store"] is False
    finally:
        await provider.close()


async def test_openai_refusal_requires_review():
    def handler(request):
        return httpx2.Response(
            200,
            json={
                "id": "resp_test",
                "object": "response",
                "created_at": 1,
                "status": "completed",
                "model": "test-model",
                "output": [
                    {
                        "id": "msg_test",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [{"type": "refusal", "refusal": "Unable to verify"}],
                    }
                ],
            },
        )

    provider = OpenAIProvider(Settings(_env_file=None, llm_api_key="test-key", llm_model="test-model"))
    await provider.client.close()
    provider.client = AsyncOpenAI(
        api_key="test-key", http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
    )
    try:
        with pytest.raises(NeedsReview):
            await provider.structured(Evaluation, "Evaluate.", {})
    finally:
        await provider.close()
