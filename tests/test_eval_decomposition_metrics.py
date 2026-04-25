from __future__ import annotations


def test_compute_decomposition_metrics_scores_partial_overlap() -> None:
    from app.rag.evaluation.metrics.decomposition import compute_decomposition_metrics

    metrics = compute_decomposition_metrics(
        [
            {
                "gold_subqueries": ["reset password", "unlock account"],
                "predicted_subqueries": ["reset password", "check account lock"],
            },
            {
                "gold_subqueries": ["check billing status"],
                "predicted_subqueries": ["check billing status"],
            },
        ]
    )

    assert metrics["evaluated"] == 2
    assert metrics["exact_match"] == 1
    assert metrics["exact_match_rate"] == 0.5
    assert metrics["precision"] == 0.75
    assert metrics["recall"] == 0.75
    assert metrics["decomposition_f1"] == 0.75


def test_compute_decomposition_metrics_ignores_rows_without_gold_subqueries() -> None:
    from app.rag.evaluation.metrics.decomposition import compute_decomposition_metrics

    metrics = compute_decomposition_metrics(
        [
            {"gold_subqueries": [], "predicted_subqueries": ["a"]},
            {"gold_subqueries": None, "predicted_subqueries": ["a"]},
            {"gold_subqueries": ["one"], "predicted_subqueries": ["one", "one"]},
        ]
    )

    assert metrics["evaluated"] == 1
    assert metrics["exact_match"] == 1
    assert metrics["exact_match_rate"] == 1.0
    assert metrics["precision"] == 1.0
    assert metrics["recall"] == 1.0
    assert metrics["decomposition_f1"] == 1.0
