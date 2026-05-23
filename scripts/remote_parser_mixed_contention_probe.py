#!/usr/bin/env python3
"""Run a mixed-backend parser contention probe against a live API."""

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
    from scripts.remote_parser_service_matrix import write_fixture_pdf
    from scripts.remote_pdf_parser_performance import Api, classify_result, summarize_body
except ModuleNotFoundError:
    ensure_repo_root_on_sys_path(__file__)
    from scripts.remote_parser_service_matrix import write_fixture_pdf
    from scripts.remote_pdf_parser_performance import Api, classify_result, summarize_body


DEFAULT_TENANT_ID = "00000000-0000-0000-0000-000000000000"


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


def summarize_backend_stats(*, backend: str, results: list[dict[str, Any]]) -> dict[str, Any]:
    latencies = [float(item.get("elapsed_sec") or 0.0) for item in results]
    success_count = sum(1 for item in results if bool(item.get("ok")))
    request_count = len(results)
    return {
        "backend": str(backend),
        "request_count": int(request_count),
        "success_count": int(success_count),
        "failure_count": int(request_count - success_count),
        "latency_p50_sec": round(percentile(latencies, 50), 3),
        "latency_p95_sec": round(percentile(latencies, 95), 3),
    }


def run_case(api: Api, *, pdf_path: Path, backend: str, min_markdown_chars: int, round_index: int) -> dict[str, Any]:
    status, body, elapsed = api.parse_preview(pdf_path, backend)
    summary = summarize_body(body)
    failure_class = classify_result(status, summary, backend, min_markdown_chars)
    return {
        "backend_requested": backend,
        "round": int(round_index),
        "status_code": int(status),
        "elapsed_sec": round(float(elapsed), 3),
        "ok": failure_class == "ok",
        "failure_class": failure_class,
        **summary,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a mixed-backend parser contention probe against a live API.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--tenant-id", default=DEFAULT_TENANT_ID)
    parser.add_argument("--account-id", default="demo")
    parser.add_argument("--user-id", default="demo")
    parser.add_argument("--artifact-dir", default="")
    parser.add_argument("--backends", default="magicpdf,marker")
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--timeout", type=int, default=1200)
    parser.add_argument("--min-markdown-chars", type=int, default=80)
    parser.add_argument("--pages", type=int, default=2)
    args = parser.parse_args()

    artifact_dir = Path(args.artifact_dir or f"artifacts/parser-contention/{time.strftime('%Y%m%d-%H%M%S')}").resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    fixture_path = artifact_dir / "parser-contention-fixture.pdf"
    write_fixture_pdf(fixture_path, pages=max(1, int(args.pages or 1)))

    api = Api(args.base_url, args.tenant_id, args.account_id, args.user_id, args.timeout)
    backends = [item.strip() for item in str(args.backends or "").split(",") if item.strip()]
    tasks = [(backend, round_idx) for round_idx in range(1, max(1, int(args.rounds or 1)) + 1) for backend in backends]

    started = time.perf_counter()
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, len(backends))) as pool:
        futures = [
            pool.submit(
                run_case,
                api,
                pdf_path=fixture_path,
                backend=backend,
                min_markdown_chars=int(args.min_markdown_chars),
                round_index=round_idx,
            )
            for backend, round_idx in tasks
        ]
        for future in as_completed(futures):
            results.append(future.result())
    elapsed = time.perf_counter() - started

    per_backend = []
    for backend in backends:
        backend_results = [item for item in results if str(item.get("backend_requested")) == backend]
        per_backend.append({**summarize_backend_stats(backend=backend, results=backend_results), "results": backend_results})

    report = {
        "ok": all(bool(item.get("ok")) for item in results),
        "artifact_dir": str(artifact_dir),
        "base_url": args.base_url,
        "fixture": {"path": str(fixture_path), "bytes": fixture_path.stat().st_size, "pages": int(args.pages)},
        "backends": backends,
        "rounds": int(args.rounds),
        "elapsed_sec": round(float(elapsed), 3),
        "throughput_rps": round((float(len(results)) / float(elapsed)) if elapsed > 0 else 0.0, 3),
        "results": sorted(results, key=lambda item: (str(item.get("backend_requested") or ""), int(item.get("round") or 0))),
        "per_backend": per_backend,
    }
    (artifact_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("ok", "artifact_dir", "backends", "rounds", "elapsed_sec", "throughput_rps")}, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
