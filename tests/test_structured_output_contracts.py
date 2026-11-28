import json

import pytest

from app.rag.llm.structured_output import parse_and_repair_structured_output


@pytest.mark.parametrize(
    "preset,fields",
    [
        ("faq", {"qa_pairs": [{"question": "Which?", "answer": "Keep | literal."}]}),
        ("summary", {"summary": "A *summary*.", "bullets": ["First", "Second"]}),
        ("action_items", {"actions": [{"item": "Ship", "owner": "alice", "due": "Friday"}]}),
    ],
)
def test_current_structured_presets_keep_their_actual_json_fields(preset, fields):
    payload, meta = parse_and_repair_structured_output(
        json.dumps({"answer": "Evidence answer", "citations": [], **fields}),
        preset=preset,
        fallback_answer="Fallback",
    )
    assert payload == {"answer": "Evidence answer", "citations": [], **fields}
    assert meta["fallback_used"] is False


def test_invalid_structured_text_reports_its_fallback():
    citations = [{"document_id": "source"}]
    payload, meta = parse_and_repair_structured_output(
        "invalid JSON", preset="faq", fallback_answer="Existing answer", fallback_citations=citations
    )
    assert payload == {"answer": "Existing answer", "citations": citations, "qa_pairs": []}
    assert meta["fallback_used"] is True


@pytest.mark.asyncio
async def test_schema_prompt_preserves_optional_defaults_without_requesting_invalid_nulls():
    from pydantic import BaseModel, Field

    from app.rag.llm.base import BaseLLMClient
    from app.rag.llm.models import LLMMessage, LLMResponse, LLMRole

    class Plan(BaseModel):
        queries: list[str] = Field(default_factory=list)

    class Client(BaseLLMClient):
        async def aclose(self):
            pass

        async def chat(self, messages, **_kwargs):
            instruction = messages[0].content
            assert "Omit optional fields" in instruction
            assert "use null" not in instruction
            return LLMResponse(content="{}")

        def chat_stream(self, *_args, **_kwargs):
            raise AssertionError("This request requires one JSON response")

    data = await Client().chat_with_schema(
        [LLMMessage(role=LLMRole.USER, content="Plan a query")],
        response_schema=Plan.model_json_schema(),
    )
    assert Plan.model_validate(data).queries == []
