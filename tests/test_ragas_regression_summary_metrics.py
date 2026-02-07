from __future__ import annotations


def test_regression_gate_summary_computes_recall_and_rates() -> None:
    from app.rag.evaluation import ragas as ragas_mod

    items = [
        {
            "item_meta": {
                "retrieval_recall": 1.0,
                "retrieval_hit_at_1": True,
                "retrieval_hit_at_3": True,
                "retrieval_mrr": 1.0,
                "retrieval_ndcg_at_10": 0.9,
                "abstain_triggered": False,
            }
        },
        {
            "item_meta": {
                "retrieval_recall": 0.0,
                "retrieval_hit_at_1": False,
                "retrieval_hit_at_3": False,
                "retrieval_mrr": 0.0,
                "retrieval_ndcg_at_10": 0.0,
                "abstain_triggered": True,
            }
        },
    ]

    summary = ragas_mod._build_regression_gate_summary(items)  # noqa: SLF001

    assert summary["retrieval_recall"] == 0.5
    assert summary["retrieval_hit_at_1"] == 0.5
    assert summary["retrieval_hit_at_3"] == 0.5
    assert summary["retrieval_mrr"] == 0.5
    assert summary["retrieval_ndcg_at_10"] == 0.45
    assert summary["abstain_rate"] == 0.5


def test_regression_gate_summary_skips_missing_values() -> None:
    from app.rag.evaluation import ragas as ragas_mod

    items = [
        {
            "item_meta": {
                "retrieval_recall": None,
                "retrieval_hit_at_1": None,
                "retrieval_mrr": None,
                "retrieval_ndcg_at_10": None,
                "abstain_triggered": False,
            }
        },
        {"item_meta": {}},
    ]

    summary = ragas_mod._build_regression_gate_summary(items)  # noqa: SLF001

    assert summary["retrieval_recall"] is None
    assert summary["retrieval_hit_at_1"] is None
    assert summary["retrieval_mrr"] is None
    assert summary["retrieval_ndcg_at_10"] is None
    assert summary["abstain_rate"] == 0.0
