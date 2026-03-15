from __future__ import annotations

import pytest


def test_merge_summary_with_regression_gate_includes_retrieval_keys() -> None:
    from app.rag.evaluation import ragas as mod

    summary = {"items": 1, "faithfulness": 0.9}
    eval_items = [
        {
            "item_meta": {
                "retrieval_recall": 0.5,
                "retrieval_hit_at_10": True,
                "retrieval_hit_at_20": True,
                "abstain_triggered": False,
            }
        }
    ]

    out = mod._merge_summary_with_regression_gate(summary, eval_items=eval_items)  # type: ignore[attr-defined]

    assert out["items"] == 1
    assert out["faithfulness"] == pytest.approx(0.9)
    assert out["retrieval_recall"] == pytest.approx(0.5)
    assert out["retrieval_hit_at_10"] == pytest.approx(1.0)
    assert out["retrieval_hit_at_20"] == pytest.approx(1.0)
    assert out["abstain_rate"] == pytest.approx(0.0)
