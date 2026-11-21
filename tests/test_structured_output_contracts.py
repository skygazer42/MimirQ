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
