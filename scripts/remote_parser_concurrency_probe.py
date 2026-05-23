#!/usr/bin/env python3
"""Run a small parser concurrency probe against a live API."""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any


def ensure_repo_root_on_sys_path(script_path: str | Path) -> str:
    repo_root = str(Path(script_path).resolve().parents[1])
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    return repo_root


try:
    from scripts.remote_pdf_parser_performance import Api, classify_result, summarize_body
except ModuleNotFoundError:
    ensure_repo_root_on_sys_path(__file__)
    from scripts.remote_pdf_parser_performance import Api, classify_result, summarize_body


DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000000"
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FIXTURES = [
    REPO_ROOT / "tests/fixtures/parsing_golden_broader/cross_page_table_pdf/input/sample.pdf",
    REPO_ROOT / "tests/fixtures/parsing_golden_broader/header_footer_noise_pdf/input/sample.pdf",
    REPO_ROOT / "tests/fixtures/parsing_golden_broader/merged_header_table_pdf/input/sample.pdf",
    REPO_ROOT / "tests/fixtures/parsing_golden_broader/mixed_layout_pdf/input/sample.pdf",
]


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(float(v) for v in values)
    if len(ordered) == 1:
        return ordered[0]
    pos = max(0.0, min(100.0, float(pct))) / 100.0 * (len(ordered) - 1)
    low = int(math.floor(pos))
    high = int(math.ceil(pos))
    if low == high:
        return ordered[low]
    weight = pos - low
    return ordered[low] * (1.0 - weight) + ordered[high] * weight


def summarize_level(*, concurrency: int, elapsed_sec: float, results: list[dict[str, Any]]) -> dict[str, Any]:
    latencies = [float(item.get("elapsed_sec") or 0.0) for item in results]
    success_count = sum(1 for item in results if bool(item.get("ok")))
    request_count = len(results)
    return {
        "concurrency": int(concurrency),
        "request_count": int(request_count),
        "success_count": int(success_count),
        "failure_count": int(request_count - success_count),
        "elapsed_sec": round(float(elapsed_sec), 3),
        "throughput_rps": round((float(request_count) / float(elapsed_sec)) if elapsed_sec > 0 else 0.0, 3),
        "latency_p50_sec": round(percentile(latencies, 50), 3),
        "latency_p95_sec": round(percentile(latencies, 95), 3),
    }


def run_case(api: Api, *, pdf_path: Path, backend: str, min_markdown_chars: int) -> dict[str, Any]:
    status, body, elapsed = api.parse_preview(pdf_path, backend)
    summary = summarize_body(body)
    failure_class = classify_result(status, summary, backend, min_markdown_chars)
    return {
        "file": str(pdf_path),
        "backend_requested": backend,
        "status_code": int(status),
        "elapsed_sec": round(float(elapsed), 3),
        "ok": failure_class == "ok",
        "failure_class": failure_class,
        **summary,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a parser concurrency probe against a live API.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--tenant-id", default=DEFAULT_TENANT_ID)
    parser.add_argument("--account-id", default="demo")
    parser.add_argument("--user-id", default="demo")
    parser.add_argument("--artifact-dir", default="")
    parser.add_argument("--backend", default="magicpdf")
    parser.add_argument("--concurrency-levels", default="1,2,4")
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--min-markdown-chars", type=int, default=80)
    parser.add_argument("--fixture-limit", type=int, default=4)
    args = parser.parse_args()

    artifact_dir = Path(args.artifact_dir or f"artifacts/parser-concurrency/{time.strftime('%Y%m%d-%H%M%S')}").resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)

    fixture_paths = [path for path in DEFAULT_FIXTURES if path.exists()][: max(1, int(args.fixture_limit or 1))]
    if not fixture_paths:
        raise FileNotFoundError("no parser concurrency fixtures found")

    api = Api(args.base_url, args.tenant_id, args.account_id, args.user_id, args.timeout)
    levels = [int(item.strip()) for item in str(args.concurrency_levels or "").split(",") if item.strip()]
    results_by_level: list[dict[str, Any]] = []

    for concurrency in levels:
        started = time.perf_counter()
        level_results: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=max(1, int(concurrency))) as pool:
            futures = [
                pool.submit(
                    run_case,
                    api,
                    pdf_path=pdf_path,
                    backend=str(args.backend),
                    min_markdown_chars=int(args.min_markdown_chars),
                )
                for pdf_path in fixture_paths
            ]
            for future in as_completed(futures):
                level_results.append(future.result())
        elapsed = time.perf_counter() - started
        results_by_level.append(
            {
                **summarize_level(concurrency=concurrency, elapsed_sec=elapsed, results=level_results),
                "results": sorted(level_results, key=lambda item: str(item.get("file") or "")),
            }
        )

    report = {
        "ok": all(all(item.get("ok") for item in level["results"]) for level in results_by_level),
        "artifact_dir": str(artifact_dir),
        "base_url": args.base_url,
        "backend": args.backend,
        "fixtures": [str(path) for path in fixture_paths],
        "levels": results_by_level,
    }
    (artifact_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("ok", "artifact_dir", "backend", "fixtures")}, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
