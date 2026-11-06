import argparse
import json
import os
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

SUITE_NAME = "perf-v1"


def _utc_compact_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the MimirQ performance harness suite.")
    default_out = str(Path("runs") / "perf" / f"{SUITE_NAME}-{_utc_compact_timestamp()}.json")
    parser.add_argument(
        "--out",
        default=default_out,
        help="Output JSON path (default: timestamped under runs/perf/).",
    )
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="Base URL for the MimirQ API (default: http://localhost:8000).",
    )
    parser.add_argument(
        "--llm-mock",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Enable LLM mock mode for this run (sets LLM_MOCK_ENABLED=1).",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=5,
        help="Iterations per case (default: 5).",
    )
    parser.add_argument(
        "--timeout-sec",
        type=float,
        default=2.0,
        help="Timeout per request in seconds (default: 2.0).",
    )
    parser.add_argument("--tenant-id", default="", help="Optional tenant id (sets X-Tenant-ID header).")
    parser.add_argument("--user-id", default="", help="Optional user/account id (sets X-User-ID header).")
    parser.add_argument("--token", default="", help="Optional bearer token (sets Authorization header).")
    parser.add_argument("--dataset-id", default="", help="Optional dataset id for retrieval-preview case.")
    parser.add_argument(
        "--query",
        default="What is MimirQ?",
        help="Query string for retrieval-preview case (default: 'What is MimirQ?').",
    )
    return parser.parse_args(argv)


def _apply_llm_mock_env(enabled: bool) -> str | None:
    action = "set" if enabled else "unset"
    try:
        if enabled:
            os.environ["LLM_MOCK_ENABLED"] = "1"
        else:
            os.environ.pop("LLM_MOCK_ENABLED", None)
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        print(f"warning: failed to {action} LLM_MOCK_ENABLED ({error})", file=sys.stderr)
        return error
    return None


def _strip_slashes(value: str) -> str:
    return value.strip().rstrip("/")


def _build_headers(*, tenant_id: str, user_id: str, token: str) -> dict[str, str]:
    headers: dict[str, str] = {"User-Agent": "mimirq-perf-harness/1.0"}
    if tenant_id:
        headers["X-Tenant-ID"] = tenant_id
    if token:
        headers["Authorization"] = f"Bearer {token}"
    elif user_id:
        headers["X-User-ID"] = user_id
    return headers


@dataclass(frozen=True)
class PerfCase:
    name: str
    method: str
    path: str
    expected_statuses: tuple[int, ...] = (200,)
    json_body: dict[str, Any] | None = None


def _run_case(
    *,
    client: httpx.Client,
    base_url: str,
    case: PerfCase,
    iterations: int,
    timeout_sec: float,
    headers: dict[str, str],
) -> dict[str, Any]:
    from app.rag.evaluation.perf_bench import bounded_top_counts, summarize_latencies_ms

    latencies_ms: list[float] = []
    status_codes: Counter[str] = Counter()
    errors: Counter[str] = Counter()
    ok_count = 0

    started = time.perf_counter()
    for _ in range(max(0, iterations)):
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
            latencies_ms.append(elapsed_ms)
            status_codes[str(resp.status_code)] += 1
            if resp.status_code in case.expected_statuses:
                ok_count += 1
        except Exception as exc:  # noqa: BLE001
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            latencies_ms.append(elapsed_ms)
            errors[type(exc).__name__] += 1

    total_sec = time.perf_counter() - started
    qps = (float(iterations) / float(total_sec)) if total_sec > 0.0 and iterations > 0 else None

    return {
        "name": case.name,
        "method": case.method,
        "path": case.path,
        "iterations": iterations,
        "ok_count": ok_count,
        "ok_ratio": ok_count / float(iterations) if iterations > 0 else 0.0,
        "qps": qps,
        "latency_ms": summarize_latencies_ms(latencies_ms),
        "status_codes": dict(status_codes),
        "errors_top": bounded_top_counts(dict(errors), max_items=10),
    }


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    llm_mock = args.llm_mock
    llm_mock_env_error = _apply_llm_mock_env(llm_mock)
    llm_mock_env = os.environ.get("LLM_MOCK_ENABLED")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    base_url = _strip_slashes(args.base_url)
    iterations = max(1, args.iterations or 5)
    timeout_sec = args.timeout_sec or 2.0

    headers = _build_headers(
        tenant_id=args.tenant_id.strip(),
        user_id=args.user_id.strip(),
        token=args.token.strip(),
    )

    cases: list[PerfCase] = [
        PerfCase(name="health", method="GET", path="/api/v1/health"),
        PerfCase(name="ready", method="GET", path="/api/v1/health/ready"),
        PerfCase(name="meta", method="GET", path="/api/v1/meta"),
    ]

    dataset_id = args.dataset_id.strip()
    if dataset_id and headers.get("X-Tenant-ID") and (headers.get("Authorization") or headers.get("X-User-ID")):
        cases.append(
            PerfCase(
                name="retrieve_preview",
                method="POST",
                path="/api/v1/rag/retrieve-preview",
                expected_statuses=(200, 400, 403),
                json_body={
                    "query": args.query or "What is MimirQ?",
                    "dataset_id": dataset_id,
                },
            )
        )

    case_results: list[dict[str, Any]] = []
    # Avoid ambient proxy env (e.g. ALL_PROXY=socks://...) affecting local perf runs.
    with httpx.Client(trust_env=False) as client:
        for case in cases:
            case_results.append(
                _run_case(
                    client=client,
                    base_url=base_url,
                    case=case,
                    iterations=iterations,
                    timeout_sec=timeout_sec,
                    headers=headers,
                )
            )

    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "suite": SUITE_NAME,
        "base_url": base_url,
        "llm_mock": llm_mock,
        "llm_mock_env": llm_mock_env,
        "llm_mock_env_error": llm_mock_env_error,
        "iterations": iterations,
        "timeout_sec": timeout_sec,
        "cases": case_results,
    }

    out_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
