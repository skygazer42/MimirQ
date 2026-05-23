from __future__ import annotations

from scripts.remote_parser_mixed_contention_probe import (
    build_timeout_result,
    parse_backend_fixture_overrides,
    summarize_backend_stats,
)


def test_remote_parser_mixed_contention_probe_summarize_backend_stats() -> None:
    summary = summarize_backend_stats(
        backend="magicpdf",
        results=[
            {"ok": True, "elapsed_sec": 10.0},
            {"ok": False, "elapsed_sec": 15.0},
            {"ok": True, "elapsed_sec": 20.0},
        ],
    )

    assert summary["backend"] == "magicpdf"
    assert summary["request_count"] == 3
    assert summary["success_count"] == 2
    assert summary["failure_count"] == 1
    assert summary["latency_p50_sec"] == 15.0
    assert summary["latency_p95_sec"] >= 19.0


def test_remote_parser_mixed_contention_probe_build_timeout_result_marks_failure() -> None:
    result = build_timeout_result(backend="olmocr", round_index=2, timeout_sec=180.0)

    assert result["backend_requested"] == "olmocr"
    assert result["round"] == 2
    assert result["ok"] is False
    assert result["failure_class"] == "timeout"
    assert result["timeout_sec"] == 180.0
    assert result["fixture_path"] is None


def test_remote_parser_mixed_contention_probe_parses_backend_fixture_overrides(tmp_path) -> None:
    fixture = tmp_path / "rfc9000.pdf"
    fixture.write_bytes(b"%PDF-1.4\n")

    overrides = parse_backend_fixture_overrides(
        [f"magicpdf={fixture}", f"deepdoc={fixture.name}"],
        cwd=tmp_path,
    )

    assert overrides["magicpdf"] == fixture.resolve()
    assert overrides["deepdoc"] == fixture.resolve()
