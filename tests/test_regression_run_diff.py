from __future__ import annotations

import uuid


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
    assert top.get("delta") == 0.5

    sd = out.get("slice_diffs") or {}
    ft = sd.get("file_type") or {}
    buckets = ft.get("buckets") or []
    assert buckets and buckets[0].get("key") == "pdf"

    m = _find_metric(buckets[0].get("metrics") or [], "retrieval_recall")
    assert m is not None
    assert m.get("delta") == 0.5

