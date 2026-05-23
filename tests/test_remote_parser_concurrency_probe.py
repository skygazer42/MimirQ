from __future__ import annotations

from scripts.remote_parser_concurrency_probe import percentile, summarize_level


def test_remote_parser_concurrency_probe_percentile_handles_small_lists() -> None:
    assert percentile([], 95) == 0.0
    assert percentile([1.0], 95) == 1.0
    assert percentile([1.0, 2.0, 3.0, 4.0], 50) == 2.5


def test_remote_parser_concurrency_probe_summarize_level_counts_success_and_throughput() -> None:
    summary = summarize_level(
        concurrency=2,
        elapsed_sec=4.0,
        results=[
            {"ok": True, "elapsed_sec": 1.2},
            {"ok": True, "elapsed_sec": 1.8},
            {"ok": False, "elapsed_sec": 0.9},
        ],
    )

    assert summary["concurrency"] == 2
    assert summary["request_count"] == 3
    assert summary["success_count"] == 2
    assert summary["failure_count"] == 1
    assert summary["throughput_rps"] == 0.75
    assert summary["latency_p50_sec"] > 0
    assert summary["latency_p95_sec"] >= summary["latency_p50_sec"]
