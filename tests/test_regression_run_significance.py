from __future__ import annotations

import pytest


def test_regression_run_significance_computes_case_paired_statistics() -> None:
    from app.services.regression_run_significance import compare_regression_items

    base_items = [
        {"case_id": "c1", "question": "q1", "scores": {"retrieval_recall": 0.0, "retrieval_hit_at_20": 0}},
        {"case_id": "c2", "question": "q2", "scores": {"retrieval_recall": 0.5, "retrieval_hit_at_20": 1}},
        {"case_id": "c3", "question": "q3", "scores": {"retrieval_recall": 0.5, "retrieval_hit_at_20": 0}},
        {"case_id": "c4", "question": "q4", "scores": {"retrieval_recall": 1.0, "retrieval_hit_at_20": 1}},
    ]
    target_items = [
        {"case_id": "c1", "question": "q1", "scores": {"retrieval_recall": 0.5, "retrieval_hit_at_20": 1}},
        {"case_id": "c2", "question": "q2", "scores": {"retrieval_recall": 0.75, "retrieval_hit_at_20": 1}},
        {"case_id": "c3", "question": "q3", "scores": {"retrieval_recall": 0.75, "retrieval_hit_at_20": 1}},
        {"case_id": "c4", "question": "q4", "scores": {"retrieval_recall": 1.0, "retrieval_hit_at_20": 1}},
    ]

    out = compare_regression_items(
        base_items=base_items,
        target_items=target_items,
        metric_keys=["retrieval_recall", "retrieval_hit_at_20"],
        bootstrap_iterations=200,
    )

    by_key = {row["key"]: row for row in out["significance"]}
    recall = by_key["retrieval_recall"]
    assert recall["compared"] == 4
    assert recall["delta_mean"] == pytest.approx(0.25)
    assert recall["bootstrap_ci_low"] <= recall["delta_mean"] <= recall["bootstrap_ci_high"]
    assert recall["p_value"] is not None
    assert recall["p_value_bh"] is not None
    assert recall["cohen_d"] is not None

    hit = by_key["retrieval_hit_at_20"]
    assert hit["mcnemar_p_value"] is not None

    case_rows = out["case_diffs"]
    assert [row["case_id"] for row in case_rows] == ["c1", "c2", "c3", "c4"]
    assert case_rows[0]["label"] == "改善"
