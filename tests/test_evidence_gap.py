from __future__ import annotations

from app.rag.retrieval.evidence_gap import detect_evidence_gap


def test_detect_evidence_gap_reports_missing_source_keys() -> None:
    out = detect_evidence_gap(
        citations=[{"table_id": "sales", "chunk_id": "c1", "document_id": "d1"}],
        required_source_keys=["inventory"],
        required_anchor_fields=["chunk_id", "document_id"],
    )
    assert out["schema"] == "mimirq.evidence_gap.v1"
    assert out["has_gap"] is True
    assert "missing_required_source_keys" in list(out.get("reason_codes") or [])
    assert list(out.get("missing_source_keys") or []) == ["inventory"]


def test_detect_evidence_gap_reports_no_gap_when_constraints_met() -> None:
    out = detect_evidence_gap(
        citations=[{"table_id": "inventory", "chunk_id": "c1", "document_id": "d1"}],
        required_source_keys=["inventory"],
        required_anchor_fields=["chunk_id", "document_id"],
    )
    assert out["has_gap"] is False
    assert list(out.get("reason_codes") or []) == []
