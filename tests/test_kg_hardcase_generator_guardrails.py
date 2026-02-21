import pytest

from app.rag.evaluation.kg_hardcase_generator import sanitize_hardcases


def test_sanitize_hardcases_dedup_and_cap() -> None:
    raw = {
        "hardcases": [
            {"kind": "knowledge_pressure", "question": "Q1", "rationale": "r1"},
            {"kind": "knowledge_pressure", "question": "Q1", "rationale": "dup"},
            {"kind": "reasoning_pressure", "question": "Q2"},
            {"kind": "reasoning_pressure", "question": "Q3"},
        ]
    }

    out = sanitize_hardcases(raw, max_items=3, max_chars=100)
    assert [h.kind for h in out] == ["knowledge_pressure", "reasoning_pressure", "reasoning_pressure"]
    assert [h.question for h in out] == ["Q1", "Q2", "Q3"]


def test_sanitize_hardcases_drops_invalid_kind_and_empty_question() -> None:
    raw = {
        "hardcases": [
            {"kind": "bogus", "question": "Q1"},
            {"kind": "knowledge_pressure", "question": ""},
            {"kind": "reasoning_pressure", "question": "Q2"},
        ]
    }
    out = sanitize_hardcases(raw, max_items=10, max_chars=100)
    assert len(out) == 1
    assert out[0].kind == "reasoning_pressure"
    assert out[0].question == "Q2"


def test_sanitize_hardcases_truncates_long_question() -> None:
    long_q = "x" * 500
    raw = {"hardcases": [{"kind": "knowledge_pressure", "question": long_q}]}
    out = sanitize_hardcases(raw, max_items=10, max_chars=120)
    assert len(out) == 1
    assert len(out[0].question) <= 120


def test_sanitize_hardcases_handles_raw_fallback_shape() -> None:
    # BaseLLMClient.chat_with_schema returns {"raw": "..."} on parse errors.
    raw = {"raw": "not json"}
    out = sanitize_hardcases(raw, max_items=10, max_chars=100)
    assert out == []


@pytest.mark.parametrize("value", [None, "", [], {}, 123])
def test_sanitize_hardcases_empty_inputs(value) -> None:
    out = sanitize_hardcases(value, max_items=10, max_chars=100)
    assert out == []

