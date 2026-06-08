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


def test_build_answer_quality_metrics_summary_includes_citation_eval_window_counts() -> None:
    from app.rag.evaluation.ragas import _build_answer_quality_metrics_summary

    out = _build_answer_quality_metrics_summary(
        [
            {
                "citation_accuracy": 0.5,
                "citation_eval_limit": 5,
                "citation_evaluated_count": 5,
                "citation_total_count": 12,
            },
            {
                "citation_accuracy": 0.25,
                "citation_eval_limit": 5,
                "citation_evaluated_count": 4,
                "citation_total_count": 8,
            },
        ]
    )

    assert out["citation_accuracy"] == pytest.approx(0.375)
    assert out["citation_eval_limit_avg"] == pytest.approx(5.0)
    assert out["citation_evaluated_count_avg"] == pytest.approx(4.5)
    assert out["citation_total_count_avg"] == pytest.approx(10.0)


def test_build_regression_gate_summary_includes_effective_context_metrics() -> None:
    from app.rag.evaluation.ragas import _build_regression_gate_summary

    out = _build_regression_gate_summary(
        [
            {"item_meta": {"retrieval_effective_context_rate": 0.5, "retrieval_noise_rate": 0.5}},
            {"item_meta": {"retrieval_effective_context_rate": 1.0, "retrieval_noise_rate": 0.0}},
        ]
    )

    assert out["retrieval_effective_context_rate"] == pytest.approx(0.75)
    assert out["retrieval_noise_rate"] == pytest.approx(0.25)
