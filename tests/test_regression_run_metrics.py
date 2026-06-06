from __future__ import annotations

import pytest

from app.rag.evaluation.evidence_retrieve_gate import build_retrieval_gate_summary


def test_retrieval_gate_summary_includes_parse_quality_slo_fields() -> None:
    summary = build_retrieval_gate_summary(
        [
            {
                "retrieval_recall": 1.0,
                "retrieval_doc_recall": 1.0,
                "retrieval_family_recall": 1.0,
                "retrieval_doc_hit": True,
                "retrieval_family_hit": True,
                "must_recall_passed": True,
                "parse_quality_alert": False,
                "parse_quality_gate_blocked": False,
                "parse_risk_level": "low",
                "parse_risk_score": 0.1,
            },
            {
                "retrieval_recall": 0.0,
                "retrieval_doc_recall": 0.0,
                "retrieval_family_recall": 0.0,
                "retrieval_doc_hit": False,
                "retrieval_family_hit": False,
                "must_recall_passed": False,
                "parse_quality_alert": True,
                "parse_quality_gate_blocked": True,
                "parse_risk_level": "high",
                "parse_risk_score": 0.9,
            },
        ]
    )
    assert summary["must_recall_pass_rate"] == pytest.approx(0.5)
    assert summary["parse_quality_alert_rate"] == pytest.approx(0.5)
    assert summary["parse_quality_gate_block_rate"] == pytest.approx(0.5)
    assert summary["parse_risk_high_cases"] == 1
    assert summary["retrieval_doc_recall"] == pytest.approx(0.5)
    assert summary["retrieval_family_recall"] == pytest.approx(0.5)
    assert summary["retrieval_doc_hit_rate"] == pytest.approx(0.5)
    assert summary["retrieval_family_hit_rate"] == pytest.approx(0.5)


def test_retrieval_gate_summary_includes_expected_metadata_metrics() -> None:
    summary = build_retrieval_gate_summary(
        [
            {
                "expected_metadata_hit": True,
                "expected_metadata_recall": 1.0,
                "expected_metadata_fields_total": 2,
                "expected_metadata_fields_matched": 2,
            },
            {
                "expected_metadata_hit": False,
                "expected_metadata_recall": 0.5,
                "expected_metadata_fields_total": 2,
                "expected_metadata_fields_matched": 1,
            },
        ]
    )

    assert summary["expected_metadata_hit_rate"] == pytest.approx(0.5)
    assert summary["expected_metadata_recall"] == pytest.approx(0.75)
    assert summary["expected_metadata_cases_total"] == 2
    assert summary["expected_metadata_fields_total"] == 4
    assert summary["expected_metadata_fields_matched"] == 3
