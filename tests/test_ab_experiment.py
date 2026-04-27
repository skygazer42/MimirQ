from __future__ import annotations

import pytest

from app.rag.evaluation.ab_experiment import assign_ab_variant, summarize_ab_results


def test_assign_ab_variant_is_stable_for_same_tenant_and_user() -> None:
    first = assign_ab_variant(
        experiment_key="retrieval-router-v1",
        tenant_id="tenant-a",
        user_id="user-1",
        variants=["baseline", "candidate"],
    )
    second = assign_ab_variant(
        experiment_key="retrieval-router-v1",
        tenant_id="tenant-a",
        user_id="user-1",
        variants=["baseline", "candidate"],
    )

    assert first["schema"] == "mimirq.ab_assignment.v1"
    assert first == second
    assert first["variant"] in {"baseline", "candidate"}


def test_summarize_ab_results_aggregates_faithfulness_and_latency_by_variant() -> None:
    summary = summarize_ab_results(
        [
            {"variant": "baseline", "faithfulness": 0.6, "latency_ms": 1200},
            {"variant": "baseline", "faithfulness": 0.8, "latency_ms": 1000},
            {"variant": "candidate", "faithfulness": 0.9, "latency_ms": 900},
            {"variant": "candidate", "faithfulness": 0.7, "latency_ms": 950},
        ]
    )

    assert summary["schema"] == "mimirq.ab_summary.v1"
    assert summary["variants"]["baseline"]["samples"] == 2
    assert summary["variants"]["candidate"]["samples"] == 2
    assert summary["variants"]["baseline"]["faithfulness_avg"] == pytest.approx(0.7)
    assert summary["variants"]["candidate"]["faithfulness_avg"] == pytest.approx(0.8)
    assert summary["variants"]["baseline"]["latency_ms_avg"] == pytest.approx(1100.0)
    assert summary["variants"]["candidate"]["latency_ms_avg"] == pytest.approx(925.0)
