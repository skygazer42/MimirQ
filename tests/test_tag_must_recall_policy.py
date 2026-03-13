from __future__ import annotations

from app.rag.policy.must_recall import (
    build_must_recall_fail_reasons,
    evaluate_required_source_keys,
    normalize_source_keys,
)


def test_normalize_source_keys_deduplicates_and_preserves_order() -> None:
    out = normalize_source_keys("sales, inventory, Sales,  ,inventory")
    assert out == ["sales", "inventory"]


def test_evaluate_required_source_keys_matches_table_and_source_fields() -> None:
    citations = [
        {"table_id": "inventory", "document_name": "inventory.xlsx"},
        {"source": "sales"},
    ]
    ev = evaluate_required_source_keys(citations=citations, required_source_keys=["inventory", "sales"])
    assert ev.get("passed") is True
    assert list(ev.get("missing_source_keys") or []) == []


def test_build_must_recall_fail_reasons_includes_secondary_pass_no_effect() -> None:
    reasons = build_must_recall_fail_reasons(
        citations_count=1,
        missing_source_keys=["inventory"],
        anchor_missing_any=0,
        second_pass_attempted=True,
        second_pass_used=False,
    )
    assert "missing_required_source_keys" in reasons
    assert "secondary_pass_no_effect" in reasons
