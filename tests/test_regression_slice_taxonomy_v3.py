from __future__ import annotations


def test_regression_slice_summaries_include_access_mode() -> None:
    # Internal helper is intentionally pure-ish and safe to unit-test.
    from app.rag.evaluation.ragas import _build_regression_slice_summaries

    eval_items = [
        {
            "item_meta": {
                "slice_access_mode": "inherit",
                "retrieval_recall": 1.0,
                "retrieval_hit_at_20": True,
                "abstain_triggered": False,
            }
        },
        {
            "item_meta": {
                "slice_access_mode": "only_me",
                "retrieval_recall": 0.0,
                "retrieval_hit_at_20": False,
                "abstain_triggered": True,
            }
        },
    ]

    out = _build_regression_slice_summaries(eval_items, max_buckets=20)
    assert "access_mode" in out
    buckets = (out.get("access_mode") or {}).get("buckets") or []
    keys = {b.get("key") for b in buckets if isinstance(b, dict)}
    assert keys == {"inherit", "only_me"}

