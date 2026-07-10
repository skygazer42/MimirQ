
import json
import os
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from app.rag.evaluation.perf_bench import bounded_top_counts, summarize_latencies_ms, utc_now_iso
from app.services.perf_suite_diff_service import diff_perf_suite_reports

PERF_SUITE_NAME = "perf-v1"
PERF_SUITE_RUN_SCHEMA_V1 = "mimirq.perf_suite_run.v1"

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_BASELINE_PATH = _REPO_ROOT / "ci" / "perf_suite_baseline.v1.json"
_DEFAULT_POLICY_PATH = _REPO_ROOT / "ci" / "perf_regression_policy.v1.json"


def _strip_slashes(value: str) -> str:
    return (value or "").strip().rstrip("/")


def _read_json(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    obj = json.loads(raw)
    if not isinstance(obj, dict):
        raise ValueError(f"Expected JSON object at: {path}")
    return obj


def _default_base_url() -> str:
    port = str(os.environ.get("PORT", "") or "").strip() or "8000"
    return f"http://127.0.0.1:{port}"


@dataclass(frozen=True)
class _PerfCase:
    name: str
    method: str
    path: str
    expected_statuses: tuple[int, ...] = (200,)
    json_body: dict[str, Any] | None = None


def _run_case(
    *,
    client: httpx.Client,
    base_url: str,
    case: _PerfCase,
    iterations: int,
    timeout_sec: float,
    headers: dict[str, str],
) -> dict[str, Any]:
    latencies_ms: list[float] = []
    status_codes: Counter[str] = Counter()
    errors: Counter[str] = Counter()
    ok_count = 0

    started = time.perf_counter()
    for _ in range(max(0, int(iterations or 0))):
        url = f"{base_url}{case.path}"
        t0 = time.perf_counter()
        try:
            resp = client.request(
                method=case.method,
                url=url,
                headers=headers,
                json=case.json_body,
                timeout=timeout_sec,
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            latencies_ms.append(float(elapsed_ms))
            status_codes[str(resp.status_code)] += 1
            if int(resp.status_code) in set(case.expected_statuses):
                ok_count += 1
        except Exception as exc:  # noqa: BLE001
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            latencies_ms.append(float(elapsed_ms))
            errors[type(exc).__name__] += 1

    total_sec = time.perf_counter() - started
    qps = (float(iterations) / float(total_sec)) if total_sec > 0.0 and iterations > 0 else None

    return {
        "name": case.name,
        "method": case.method,
        "path": case.path,
        "iterations": int(iterations),
        "ok_count": int(ok_count),
        "ok_ratio": float(ok_count / float(iterations)) if iterations > 0 else 0.0,
        "qps": float(qps) if qps is not None else None,
        "latency_ms": summarize_latencies_ms(latencies_ms),
        "status_codes": dict(status_codes),
        "errors_top": bounded_top_counts(dict(errors), max_items=10),
    }


def run_minimal_perf_suite_report(
    *,
    base_url: str | None = None,
    iterations: int = 10,
    timeout_sec: float = 2.0,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """
    Run a minimal, PII-safe perf suite against the local API.

    Cases are intentionally small and stable:
    - /health
    - /health/ready
    - /meta

    This is meant for diagnostics and CI gating (p95/p99 regression checks).
    """
    base = _strip_slashes(base_url or _default_base_url())
    iters = max(1, int(iterations or 0))
    timeout = float(timeout_sec or 0.0)
    hdrs = dict(headers or {})

    cases: list[_PerfCase] = [
        _PerfCase(name="health", method="GET", path="/api/v1/health"),
        _PerfCase(name="ready", method="GET", path="/api/v1/health/ready"),
        _PerfCase(name="meta", method="GET", path="/api/v1/meta"),
    ]

    case_results: list[dict[str, Any]] = []
    client_timeout = timeout if timeout > 0.0 else None
    with httpx.Client(trust_env=False, timeout=client_timeout) as client:
        for case in cases:
            case_results.append(
                _run_case(
                    client=client,
                    base_url=base,
                    case=case,
                    iterations=iters,
                    timeout_sec=timeout,
                    headers=hdrs,
                )
            )

    return {
        "ts": utc_now_iso(),
        "suite": PERF_SUITE_NAME,
        "base_url": base,
        "iterations": int(iters),
        "timeout_sec": float(timeout),
        "cases": case_results,
    }


def run_minimal_perf_suite_report_and_diff(
    *,
    baseline_path: Path | None = None,
    policy_path: Path | None = None,
    base_url: str | None = None,
    iterations: int = 10,
    timeout_sec: float = 2.0,
) -> dict[str, Any]:
    baseline_file = Path(baseline_path) if baseline_path is not None else _DEFAULT_BASELINE_PATH
    policy_file = Path(policy_path) if policy_path is not None else _DEFAULT_POLICY_PATH

    baseline = _read_json(baseline_file)
    policy = _read_json(policy_file)
    current = run_minimal_perf_suite_report(base_url=base_url, iterations=iterations, timeout_sec=timeout_sec)
    diff = diff_perf_suite_reports(baseline=baseline, current=current, policy=policy)

    return {
        "schema": PERF_SUITE_RUN_SCHEMA_V1,
        "baseline_path": str(baseline_file),
        "policy_path": str(policy_file),
        "baseline_ts": str(baseline.get("ts") or ""),
        "current_report": current,
        "diff": diff,
    }


__all__ = [
    "PERF_SUITE_NAME",
    "PERF_SUITE_RUN_SCHEMA_V1",
    "run_minimal_perf_suite_report",
    "run_minimal_perf_suite_report_and_diff",
]
