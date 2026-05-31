from __future__ import annotations

from typing import Any

from app.rag.evaluation.graphrag_bench import summarize_graphrag_bench


def run_graphrag_bench_runner(rows: list[dict[str, Any]], *, benchmark_name: str) -> dict[str, Any]:
    report = summarize_graphrag_bench(list(rows or []))
    return {
        "schema": "mimirq.graphrag_bench_runner.v1",
        "benchmark_name": str(benchmark_name or "").strip(),
        "compared_systems": sorted((report.get("systems") or {}).keys()),
        "report": report,
    }


__all__ = ["run_graphrag_bench_runner"]
