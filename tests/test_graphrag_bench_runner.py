from __future__ import annotations

from app.rag.evaluation.graphrag_bench_runner import run_graphrag_bench_runner


def test_run_graphrag_bench_runner_wraps_summary_with_runner_schema() -> None:
    out = run_graphrag_bench_runner(
        [
            {"system": "vanilla", "recall": 0.42, "cost_usd": 0.010, "latency_ms": 800},
            {"system": "mimirq_kg", "recall": 0.63, "cost_usd": 0.018, "latency_ms": 1200},
            {"system": "lightrag", "recall": 0.58, "cost_usd": 0.012, "latency_ms": 950},
        ],
        benchmark_name="graphrag-bench-mini",
    )

    assert out["schema"] == "mimirq.graphrag_bench_runner.v1"
    assert out["benchmark_name"] == "graphrag-bench-mini"
    assert out["compared_systems"] == ["lightrag", "mimirq_kg", "vanilla"]
    assert out["report"]["summary"]["best_recall_system"] == "mimirq_kg"


def test_run_graphrag_bench_runner_handles_empty_rows() -> None:
    out = run_graphrag_bench_runner([], benchmark_name="graphrag-bench-mini")

    assert out["schema"] == "mimirq.graphrag_bench_runner.v1"
    assert out["compared_systems"] == []
    assert out["report"]["summary"]["systems_compared"] == 0
