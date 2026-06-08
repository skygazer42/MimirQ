from __future__ import annotations


def test_regression_metric_split_keeps_ragas_and_deterministic_metrics_separate() -> None:
    from app.rag.evaluation.ragas import (
        DETERMINISTIC_REGRESSION_METRICS,
        split_regression_metric_names,
    )

    split = split_regression_metric_names(
        [
            "faithfulness",
            "citation_accuracy",
            "retrieval_effective_context_rate",
            "retrieval_noise_rate",
            "hallucination_rate",
            "response_relevancy",
            "quote_verifiability",
            "expected_metadata_hit_rate",
            "expected_metadata_recall",
        ]
    )

    assert "citation_accuracy" in DETERMINISTIC_REGRESSION_METRICS
    assert "retrieval_effective_context_rate" in DETERMINISTIC_REGRESSION_METRICS
    assert "retrieval_noise_rate" in DETERMINISTIC_REGRESSION_METRICS
    assert "hallucination_rate" in DETERMINISTIC_REGRESSION_METRICS
    assert "quote_verifiability" in DETERMINISTIC_REGRESSION_METRICS
    assert "expected_metadata_hit_rate" in DETERMINISTIC_REGRESSION_METRICS
    assert "expected_metadata_recall" in DETERMINISTIC_REGRESSION_METRICS
    assert split.ragas == ["faithfulness", "response_relevancy"]
    assert split.deterministic == [
        "citation_accuracy",
        "retrieval_effective_context_rate",
        "retrieval_noise_rate",
        "hallucination_rate",
        "quote_verifiability",
        "expected_metadata_hit_rate",
        "expected_metadata_recall",
    ]


def test_selected_deterministic_scores_maps_product_metric_aliases() -> None:
    from app.rag.evaluation.ragas import build_selected_deterministic_scores

    scores = build_selected_deterministic_scores(
        [
            "atomic_faithfulness",
            "hallucination_rate",
            "citation_coverage",
            "retrieval_effective_context_rate",
            "retrieval_noise_rate",
            "quote_verifiability",
            "expected_metadata_hit_rate",
            "expected_metadata_recall",
        ],
        {
            "faithfulness_det": 0.75,
            "hallucination_rate": 0.25,
            "citation_coverage": 0.5,
            "retrieval_effective_context_rate": 0.75,
            "retrieval_noise_rate": 0.25,
            "quote_verifiability": 1.0,
            "expected_metadata_hit": True,
            "expected_metadata_recall": 0.8,
        },
    )

    assert scores == {
        "atomic_faithfulness": 0.75,
        "hallucination_rate": 0.25,
        "citation_coverage": 0.5,
        "retrieval_effective_context_rate": 0.75,
        "retrieval_noise_rate": 0.25,
        "quote_verifiability": 1.0,
        "expected_metadata_hit_rate": 1.0,
        "expected_metadata_recall": 0.8,
    }
