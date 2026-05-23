from __future__ import annotations

from pathlib import Path

from scripts.remote_parser_concurrency_probe import percentile, resolve_fixture_paths, summarize_level


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


def test_remote_parser_concurrency_probe_resolve_fixture_paths_prefers_explicit_csv(tmp_path: Path) -> None:
    a = tmp_path / "a.pdf"
    b = tmp_path / "b.pdf"
    a.write_bytes(b"a")
    b.write_bytes(b"b")

    resolved = resolve_fixture_paths(default_fixtures=[tmp_path / "missing.pdf"], explicit_csv=f"{a},{b}", fixture_limit=4)

    assert resolved == [a.resolve(), b.resolve()]
