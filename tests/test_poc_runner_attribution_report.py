from __future__ import annotations

from app.rag.evaluation.poc_runner.reports.attribution_report import (
    DatasetAnalysisReportPayload,
    build_dataset_analysis_report,
)


def test_build_dataset_analysis_report_combines_metrics_examples_and_heatmap() -> None:
    report = build_dataset_analysis_report(DatasetAnalysisReportPayload(
        dataset_id="ds-1",
        dataset_name="Dataset One",
        filters={"dataset_id": "ds-1"},
        scope_summary={"all_interactions": 20, "feedback_interactions": 10, "attributable_feedback_interactions": 4},
        metrics={"raw_positive_rate": 0.7, "feedback_coverage_rate": 0.5},
        counts={"retrieval_miss": 2, "generation_error": 1, "out_of_scope": 1},
        ratios={"retrieval_miss": 0.5, "generation_error": 0.25, "out_of_scope": 0.25},
        top_examples={"retrieval_miss": [{"interaction_id": "req-1"}]},
        manual_review_candidates=[{"interaction_id": "req-2"}],
        glossary_candidates=[{"token": "485"}],
        keyword_scores=[{"token": "485", "score": 3.0}],
        coverage_heatmap={"rows": [{"filename": "manual-a.pdf", "retrieval_hit_count": 3, "negative_feedback_count": 2}]},
        umap_scatter={"schema": "mimirq.dataset_analysis.umap_scatter.v1", "points": [{"x": 0.0, "y": 1.0}]},
        latency_breakdown={"schema": "mimirq.poc.latency_decomposer.v1", "summary": {"avg_wait_in_queue_ms": 1200}},
    ))

    assert report["meta"]["dataset_id"] == "ds-1"
    assert report["meta"]["dataset_name"] == "Dataset One"
    assert report["metrics"]["raw_positive_rate"] == 0.7
    assert [item["key"] for item in report["metric_cards"]] == [
        "raw_positive_rate",
        "controllable_positive_rate",
        "knowledge_base_coverage",
        "retrieval_accuracy",
        "generation_accuracy",
    ]
    assert report["feedback_coverage"]["key"] == "feedback_coverage_rate"
    assert report["coverage_heatmap"]["rows"][0]["filename"] == "manual-a.pdf"
    assert report["umap_scatter"]["schema"] == "mimirq.dataset_analysis.umap_scatter.v1"
    assert report["latency_breakdown"]["summary"]["avg_wait_in_queue_ms"] == 1200
    assert report["top_examples"]["retrieval_miss"][0]["interaction_id"] == "req-1"
