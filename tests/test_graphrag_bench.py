from __future__ import annotations

import pytest

from app.rag.evaluation.graphrag_bench import summarize_graphrag_bench


def test_summarize_graphrag_bench_compares_recall_cost_and_latency() -> None:
    out = summarize_graphrag_bench(
        [
            {"system": "vanilla", "recall": 0.42, "cost_usd": 0.010, "latency_ms": 800},
            {"system": "mimirq_kg", "recall": 0.63, "cost_usd": 0.018, "latency_ms": 1200},
            {"system": "lightrag", "recall": 0.58, "cost_usd": 0.012, "latency_ms": 950},
        ]
    )

    assert out["schema"] == "mimirq.graphrag_bench.v1"
    assert out["summary"]["systems_compared"] == 3
    assert out["summary"]["best_recall_system"] == "mimirq_kg"
    assert out["summary"]["lowest_cost_system"] == "vanilla"
    assert out["summary"]["fastest_system"] == "vanilla"
    assert out["systems"]["mimirq_kg"]["recall"] == pytest.approx(0.63)
    assert out["systems"]["mimirq_kg"]["cost_usd"] == pytest.approx(0.018)


def test_summarize_graphrag_bench_computes_cost_efficiency() -> None:
    out = summarize_graphrag_bench(
        [
            {"system": "vanilla", "recall": 0.42, "cost_usd": 0.010, "latency_ms": 800},
            {"system": "mimirq_kg", "recall": 0.63, "cost_usd": 0.018, "latency_ms": 1200},
            {"system": "lightrag", "recall": 0.58, "cost_usd": 0.012, "latency_ms": 950},
        ]
    )

    assert out["summary"]["best_cost_efficiency_system"] == "lightrag"
    assert out["systems"]["lightrag"]["recall_per_cost"] == pytest.approx(48.3333, abs=1e-4)
