from __future__ import annotations

from app.rag.policy.must_recall import (
    build_must_recall_fail_reasons,
    evaluate_required_source_keys,
    normalize_source_keys,
)
from app.rag.policy.must_recall_auto import infer_expected_source_keys, infer_required_anchor_fields


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


def test_infer_expected_source_keys_from_query_and_metadata_filter() -> None:
    out = infer_expected_source_keys(
        query='统计 "inventory" 和 sales.orders 在 report.xlsx 的结果',
        metadata_filter={"table_id": ["inventory"], "sheet_name": "Sheet1"},
        max_keys=8,
    )
    keys = list(out.get("expected_source_keys") or [])
    assert "inventory" in keys
    assert any("sales.orders" == k for k in keys)
    assert any("report.xlsx" == k for k in keys)
    assert str(out.get("confidence") or "") in {"medium", "high"}


def test_infer_required_anchor_fields_adds_row_level_fields_for_row_intent() -> None:
    out = infer_required_anchor_fields(
        query="请告诉我是数据库哪一行",
        default_fields=["chunk_id", "document_id"],
    )
    fields = list(out.get("required_anchor_fields") or [])
    assert "chunk_id" in fields
    assert "document_id" in fields
    assert "row_source_pk_hashes" in fields
    assert bool(out.get("applied")) is True


def test_infer_expected_source_keys_includes_scope_document_ids() -> None:
    out = infer_expected_source_keys(
        query="请仅使用我限定的文档范围",
        scope={"document_ids": ["doc-1", "doc-2"]},
        max_keys=8,
    )
    keys = list(out.get("expected_source_keys") or [])
    assert "doc-1" in keys
    assert "doc-2" in keys
    assert "scope" in list(out.get("reason_codes") or [])
