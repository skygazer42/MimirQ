from __future__ import annotations

from app.rag.evaluation.metrics.fusion import compute_fusion_metrics


def test_compute_fusion_metrics_reports_conflict_rate_and_net_gain() -> None:
    metrics = compute_fusion_metrics(
        [
            {
                "retrieval_score": 0.7,
                "kg_score": 0.6,
                "hybrid_score": 0.8,
                "has_conflict": False,
            },
            {
                "retrieval_score": 0.5,
                "kg_score": 0.4,
                "hybrid_score": 0.45,
                "has_conflict": True,
            },
        ]
    )

    assert metrics["conflict_rate"] == 0.5
    assert metrics["net_gain_over_best_single"] == 0.025
