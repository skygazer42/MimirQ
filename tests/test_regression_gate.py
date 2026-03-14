from __future__ import annotations

import pytest


def test_build_answer_quality_metrics_summary_from_item_meta() -> None:
    from app.rag.evaluation.ragas import _build_answer_quality_metrics_summary

    out = _build_answer_quality_metrics_summary(
        [
            {
                "faithfulness_det": 0.8,
                "expected_refusal": False,
                "abstain_triggered": False,
            },
            {
                "faithfulness_det": 0.6,
                "expected_refusal": True,
                "abstain_triggered": False,
            },
        ]
    )
    assert float(out.get("faithfulness_det") or 0.0) > 0.0
    assert float(out.get("faithfulness") or 0.0) > 0.0
    assert float(out.get("refusal_correctness") or 0.0) == pytest.approx(0.5)
    assert float(out.get("refusal_false_negative_rate") or 0.0) == pytest.approx(0.5)
