from __future__ import annotations

from app.rag.core.text import build_abstain_answer_message, build_abstain_followup


def test_build_abstain_followup_handles_out_of_scope_reason() -> None:
    payload = build_abstain_followup(reason="out_of_scope", citations=[])

    assert payload["type"] == "refine_query"
    assert "outside the current knowledge base" in payload["question"]
    assert payload["options"] == []


def test_build_abstain_answer_message_handles_out_of_scope_reason() -> None:
    assert build_abstain_answer_message("out_of_scope") == "This question appears to be outside the current knowledge base."
