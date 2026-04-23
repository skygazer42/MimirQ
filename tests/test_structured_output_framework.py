from __future__ import annotations

from app.rag.llm.structured_output import (
    build_structured_output_instructions,
    parse_and_repair_structured_output,
)


def test_build_structured_output_instructions_uses_preset_schema() -> None:
    text = build_structured_output_instructions("summary")
    assert "Output JSON only" in text
    assert '"answer": "string"' in text
    assert '"bullets": ["point 1", "point 2"]' in text
    assert '"summary": "concise summary"' in text


def test_parse_and_repair_structured_output_repairs_partial_payload() -> None:
    payload, meta = parse_and_repair_structured_output(
        '{"answer":"done"}',
        preset="action_items",
        fallback_answer="fallback",
        fallback_citations=[{"document_id": "doc-1", "chunk_id": "chunk-1"}],
    )

    assert payload["answer"] == "done"
    assert payload["actions"] == []
    assert payload["citations"] == [{"document_id": "doc-1", "chunk_id": "chunk-1"}]
    assert meta["ok"] is True
    assert meta["repaired"] is True
    assert meta["schema_key"] == "action_items"


def test_parse_and_repair_structured_output_falls_back_when_json_invalid() -> None:
    payload, meta = parse_and_repair_structured_output(
        "not-json",
        preset="summary",
        fallback_answer="Unable to answer",
        fallback_citations=[{"document_id": "doc-2", "chunk_id": "chunk-2"}],
    )

    assert payload == {
        "answer": "Unable to answer",
        "citations": [{"document_id": "doc-2", "chunk_id": "chunk-2"}],
        "bullets": [],
        "summary": "",
    }
    assert meta["ok"] is False
    assert meta["repaired"] is True
    assert meta["fallback_used"] is True
