from __future__ import annotations

import pytest


def test_aggregate_parse_risk_summary_counts_and_recommendation() -> None:
    from app.services.report_service import _aggregate_parse_risk_summary

    summary = _aggregate_parse_risk_summary(
        total_documents=4,
        metadatas=[
            {"document_id": "d-low-1", "parse_quality": {"score": 0.1}},
            {"document_id": "d-low-2", "parse_quality": {"score": 0.2}},
            {"document_id": "d-mid", "parse_quality": {"score": 0.45}},
            {"document_id": "d-good", "parse_quality": {"score": 0.9}},
        ],
        truncated=False,
        low_threshold=0.35,
    )

    assert int(summary.total_documents or 0) == 4
    assert int(summary.considered_documents or 0) == 4
    assert int(summary.high_risk_documents or 0) == 2
    assert int(summary.medium_risk_documents or 0) == 1
    assert int(summary.healthy_documents or 0) == 1
    assert float(summary.high_risk_ratio or 0.0) == pytest.approx(0.5)
    assert str(summary.recommendation or "") == "medium_parse_risk_prioritize_low_quality_docs"
    assert [x.document_id for x in summary.top_low_quality_documents] == ["d-low-1", "d-low-2"]


def test_aggregate_parse_risk_summary_handles_missing_parse_quality() -> None:
    from app.services.report_service import _aggregate_parse_risk_summary

    summary = _aggregate_parse_risk_summary(
        total_documents=2,
        metadatas=[{"document_id": "d-1"}, {"document_id": "d-2", "parse_quality": None}],
        truncated=False,
        low_threshold=0.35,
    )

    assert int(summary.considered_documents or 0) == 0
    assert str(summary.recommendation or "") == "no_parse_quality_metadata"
    assert summary.top_low_quality_documents == []
