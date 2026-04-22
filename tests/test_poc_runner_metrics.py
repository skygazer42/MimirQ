from __future__ import annotations

from app.rag.evaluation.poc_runner.metrics import compute_feedback_metrics


def test_compute_feedback_metrics_emits_core_quality_rates() -> None:
    metrics = compute_feedback_metrics(
        all_interactions=20,
        feedback_interactions=10,
        counts={
            "retrieval_miss": 1,
            "generation_error": 1,
            "out_of_scope": 1,
        },
    )

    assert metrics["raw_positive_rate"] == 0.7
    assert metrics["controllable_positive_rate"] == 0.8
    assert metrics["knowledge_base_coverage"] == 0.9
    assert metrics["retrieval_accuracy"] == 0.9
    assert metrics["generation_accuracy"] == 0.9
    assert metrics["feedback_coverage_rate"] == 0.5
