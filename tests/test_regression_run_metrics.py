from __future__ import annotations

import pytest

from app.rag.evaluation.evidence_retrieve_gate import build_retrieval_gate_summary


def test_retrieval_gate_summary_includes_parse_quality_slo_fields() -> None:
    summary = build_retrieval_gate_summary(
        [
            {
                "retrieval_recall": 1.0,
                "must_recall_passed": True,
                "parse_quality_alert": False,
                "parse_quality_gate_blocked": False,
                "parse_risk_level": "low",
                "parse_risk_score": 0.1,
            },
            {
                "retrieval_recall": 0.0,
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
