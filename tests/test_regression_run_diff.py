from __future__ import annotations

import uuid

import pytest


def _find_metric(metrics: list[dict], key: str) -> dict | None:
    for m in metrics:
        if isinstance(m, dict) and m.get("key") == key:
            return m
    return None


def test_diff_regression_run_summaries_includes_top_level_and_slice_diffs() -> None:
    from app.services.regression_run_diff import diff_regression_run_summaries

    base_id = uuid.uuid4()
    target_id = uuid.uuid4()

    base_summary = {
        "items": 2,
        "retrieval_recall": 0.5,
        "retrieval_hit_at_20": 0.5,
        "retrieval_slices": {
            "file_type": {"buckets": [{"key": "pdf", "items": 2, "retrieval_recall": 0.5, "retrieval_hit_at_20": 0.5}]},
            "language": {"buckets": []},
            "directory": {"buckets": []},
        },
    }
    target_summary = {
        "items": 2,
        "retrieval_recall": 1.0,
        "retrieval_hit_at_20": 1.0,
        "retrieval_slices": {
            "file_type": {"buckets": [{"key": "pdf", "items": 2, "retrieval_recall": 1.0, "retrieval_hit_at_20": 1.0}]},
            "language": {"buckets": []},
            "directory": {"buckets": []},
        },
    }

    out = diff_regression_run_summaries(
        base_run_id=base_id,
        target_run_id=target_id,
        base_summary=base_summary,
        target_summary=target_summary,
        max_slice_buckets=20,
    )

    assert out["base_run_id"] == str(base_id)
    assert out["target_run_id"] == str(target_id)

    top = _find_metric(out.get("metric_diffs") or [], "retrieval_recall")
    assert top is not None
    assert top.get("delta") == pytest.approx(0.5)

    sd = out.get("slice_diffs") or {}
    ft = sd.get("file_type") or {}
    buckets = ft.get("buckets") or []
    assert buckets and buckets[0].get("key") == "pdf"

    m = _find_metric(buckets[0].get("metrics") or [], "retrieval_recall")
    assert m is not None
    assert m.get("delta") == pytest.approx(0.5)


def test_diff_regression_run_summaries_includes_access_mode_slice_diff() -> None:
    from app.services.regression_run_diff import diff_regression_run_summaries

    base_id = uuid.uuid4()
    target_id = uuid.uuid4()

    base_summary = {
        "items": 2,
        "retrieval_recall": 0.5,
        "retrieval_slices": {
            "file_type": {"buckets": []},
            "language": {"buckets": []},
            "directory": {"buckets": []},
            "access_mode": {"buckets": [{"key": "inherit", "items": 2, "retrieval_recall": 0.5}]},
        },
    }
    target_summary = {
        "items": 2,
        "retrieval_recall": 1.0,
        "retrieval_slices": {
            "file_type": {"buckets": []},
            "language": {"buckets": []},
            "directory": {"buckets": []},
            "access_mode": {"buckets": [{"key": "inherit", "items": 2, "retrieval_recall": 1.0}]},
        },
    }

    out = diff_regression_run_summaries(
        base_run_id=base_id,
        target_run_id=target_id,
        base_summary=base_summary,
        target_summary=target_summary,
        max_slice_buckets=20,
    )

    sd = out.get("slice_diffs") or {}
    am = sd.get("access_mode") or {}
    buckets = am.get("buckets") or []
    assert buckets and buckets[0].get("key") == "inherit"

    m = _find_metric(buckets[0].get("metrics") or [], "retrieval_recall")
    assert m is not None
    assert m.get("delta") == pytest.approx(0.5)


def test_diff_regression_run_summaries_includes_compact_diff_score() -> None:
    from app.services.regression_run_diff import diff_regression_run_summaries

    base_id = uuid.uuid4()
    target_id = uuid.uuid4()

    base_summary = {
        "retrieval_recall": 0.5,
        "retrieval_ndcg_at_10": 0.1,
        "faithfulness_det": 0.6,
    }
    target_summary = {
        "retrieval_recall": 1.0,
        "retrieval_ndcg_at_10": 0.2,
        "faithfulness_det": 0.9,
    }

    out = diff_regression_run_summaries(
        base_run_id=base_id,
        target_run_id=target_id,
        base_summary=base_summary,
        target_summary=target_summary,
    )

    score = out.get("diff_score") or {}
    assert score.get("version") == "1"
    assert "retrieval_recall" in (score.get("used_metric_keys") or [])
    assert score.get("delta") is not None
    assert float(score.get("delta") or 0.0) > 0.0
