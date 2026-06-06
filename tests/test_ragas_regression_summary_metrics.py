from __future__ import annotations

import pytest


def test_regression_gate_summary_computes_recall_and_rates() -> None:
    from app.rag.evaluation import ragas as ragas_mod

    items = [
        {
            "item_meta": {
                "retrieval_recall": 1.0,
                "retrieval_hit_at_1": True,
                "retrieval_hit_at_3": True,
                "retrieval_hit_at_20": True,
                "retrieval_mrr": 1.0,
                "retrieval_ndcg_at_10": 0.9,
                "retrieval_ndcg_at_20": 0.9,
                "abstain_triggered": False,
            }
        },
        {
            "item_meta": {
                "retrieval_recall": 0.0,
                "retrieval_hit_at_1": False,
                "retrieval_hit_at_3": False,
                "retrieval_hit_at_20": False,
                "retrieval_mrr": 0.0,
                "retrieval_ndcg_at_10": 0.0,
                "retrieval_ndcg_at_20": 0.0,
                "abstain_triggered": True,
            }
        },
    ]

    summary = ragas_mod._build_regression_gate_summary(items)  # noqa: SLF001

    assert summary["retrieval_recall"] == pytest.approx(0.5)
    assert summary["retrieval_hit_at_1"] == pytest.approx(0.5)
    assert summary["retrieval_hit_at_3"] == pytest.approx(0.5)
    assert summary["retrieval_hit_at_20"] == pytest.approx(0.5)
    assert summary["retrieval_mrr"] == pytest.approx(0.5)
    assert summary["retrieval_ndcg_at_10"] == pytest.approx(0.45)
    assert summary["retrieval_ndcg_at_20"] == pytest.approx(0.45)
    assert summary["abstain_rate"] == pytest.approx(0.5)


def test_regression_gate_summary_skips_missing_values() -> None:
    from app.rag.evaluation import ragas as ragas_mod

    items = [
        {
            "item_meta": {
                "retrieval_recall": None,
                "retrieval_hit_at_1": None,
                "retrieval_hit_at_20": None,
                "retrieval_mrr": None,
                "retrieval_ndcg_at_10": None,
                "retrieval_ndcg_at_20": None,
                "abstain_triggered": False,
            }
        },
        {"item_meta": {}},
    ]

    summary = ragas_mod._build_regression_gate_summary(items)  # noqa: SLF001

    assert summary["retrieval_recall"] is None
    assert summary["retrieval_hit_at_1"] is None
    assert summary["retrieval_hit_at_20"] is None
    assert summary["retrieval_mrr"] is None
    assert summary["retrieval_ndcg_at_10"] is None
    assert summary["retrieval_ndcg_at_20"] is None
    assert summary["abstain_rate"] == pytest.approx(0.0)


def test_regression_gate_summary_includes_expected_metadata_metrics() -> None:
    from app.rag.evaluation import ragas as ragas_mod

    items = [
        {
            "item_meta": {
                "expected_metadata_hit": True,
                "expected_metadata_recall": 1.0,
                "expected_metadata_fields_total": 2,
                "expected_metadata_fields_matched": 2,
            }
        },
        {
            "item_meta": {
                "expected_metadata_hit": False,
                "expected_metadata_recall": 0.5,
                "expected_metadata_fields_total": 2,
                "expected_metadata_fields_matched": 1,
            }
        },
    ]

    summary = ragas_mod._build_regression_gate_summary(items)  # noqa: SLF001

    assert summary["expected_metadata_hit_rate"] == pytest.approx(0.5)
    assert summary["expected_metadata_recall"] == pytest.approx(0.75)
    assert summary["expected_metadata_cases_total"] == 2
    assert summary["expected_metadata_fields_total"] == 4
    assert summary["expected_metadata_fields_matched"] == 3
