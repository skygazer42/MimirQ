"""
SLO/SLI snapshot builder (admin-only, PII-safe).

Sources (priority order):
1) Prometheus HTTP API (when PROMETHEUS_QUERY_BASE_URL is configured)
2) Metrics JSONL aggregates (fallback)
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx

from app.core.config import settings
from app.rag.core.logging import get_logger
from app.services.rag_metrics_dashboard import summarize_rag_query_analytics

SLO_SNAPSHOT_SCHEMA_V1 = "mimirq.slo_snapshot.v1"


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _base_url() -> str:
    raw = str(getattr(settings, "PROMETHEUS_QUERY_BASE_URL", "") or "").strip()
    return raw.rstrip("/")


def _timeout() -> float:
    try:
        return max(0.5, float(getattr(settings, "PROMETHEUS_QUERY_TIMEOUT_SEC", 3.0) or 3.0))
    except Exception:
        return 3.0


def _safe_float(v: object) -> float | None:
    try:
        f = float(v)  # type: ignore[arg-type]
    except Exception:
        return None
    if not math.isfinite(f):
        return None
    return f


async def _prom_query(client: httpx.AsyncClient, *, base_url: str, promql: str) -> float | None:
    if not base_url:
        return None
    q = str(promql or "").strip()
    if not q:
        return None

    url = f"{base_url}/api/v1/query"
    resp = await client.get(url, params={"query": q})
    resp.raise_for_status()
    data = resp.json() if resp.content else {}

    if str(data.get("status") or "") != "success":
        return None

    result = ((data.get("data") or {}) if isinstance(data.get("data"), dict) else {}).get("result")
    if not isinstance(result, list) or not result:
        return None

    # We expect a single scalar/vector element after sum()/histogram_quantile().
    # If multiple series appear, sum values best-effort.
    values: list[float] = []
    for item in result:
        if not isinstance(item, dict):
            continue
        pair = item.get("value")
        if not (isinstance(pair, list) and len(pair) >= 2):
            continue
        fv = _safe_float(pair[1])
        if fv is None:
            continue
        values.append(fv)

    if not values:
        return None
    if len(values) == 1:
        return values[0]
    return float(sum(values))


@dataclass(frozen=True)
class SloWindowSnapshot:
    window_minutes: int
    source: str
    rag_trace_count: int | None = None
    retrieval_p95_elapsed_sec: float | None = None
    retrieval_p99_elapsed_sec: float | None = None
    zero_hit_rate: float | None = None
    error_rate: float | None = None


async def _build_window_from_prometheus(*, window_minutes: int) -> SloWindowSnapshot | None:
    base = _base_url()
    if not base:
        return None

    w = max(1, int(window_minutes or 0))
    rng = f"{w}m"

    # Denominator: request count from histogram counter (count).
    req_count_q = f"sum(increase(rag_citations_count_count[{rng}]))"

    zero_hit_q = f"sum(increase(rag_zero_hit_total[{rng}])) / {req_count_q}"
    err_rate_q = f"sum(increase(rag_errors_total[{rng}])) / {req_count_q}"

    p95_q = f"histogram_quantile(0.95, sum(rate(rag_retrieval_elapsed_seconds_bucket[{rng}])) by (le))"
    p99_q = f"histogram_quantile(0.99, sum(rate(rag_retrieval_elapsed_seconds_bucket[{rng}])) by (le))"

    timeout = httpx.Timeout(_timeout())
    async with httpx.AsyncClient(timeout=timeout) as client:
        req_count = await _prom_query(client, base_url=base, promql=req_count_q)
        zero_hit_rate = await _prom_query(client, base_url=base, promql=zero_hit_q)
        err_rate = await _prom_query(client, base_url=base, promql=err_rate_q)
        p95 = await _prom_query(client, base_url=base, promql=p95_q)
        p99 = await _prom_query(client, base_url=base, promql=p99_q)

    return SloWindowSnapshot(
        window_minutes=w,
        source="prometheus",
        rag_trace_count=(int(req_count) if req_count is not None and req_count >= 0 else None),
        retrieval_p95_elapsed_sec=p95,
        retrieval_p99_elapsed_sec=p99,
        zero_hit_rate=zero_hit_rate,
        error_rate=err_rate,
    )


def _build_window_from_metrics_jsonl(*, tenant_id: str | None, window_minutes: int) -> SloWindowSnapshot:
    summary = summarize_rag_query_analytics(tenant_id=tenant_id, window_minutes=window_minutes)

    errors = summary.timeseries.get("errors") if isinstance(summary.timeseries, dict) else None
    error_count = 0
    if isinstance(errors, list):
        for v in errors:
            try:
                error_count += int(v or 0)
            except Exception:
                get_logger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
                continue

    error_rate = (float(error_count) / float(summary.rag_trace_count)) if summary.rag_trace_count else None

    return SloWindowSnapshot(
        window_minutes=int(summary.window_minutes),
        source="metrics_jsonl",
        rag_trace_count=int(summary.rag_trace_count),
        retrieval_p95_elapsed_sec=summary.retrieval_p95_elapsed_sec,
        retrieval_p99_elapsed_sec=summary.retrieval_p99_elapsed_sec,
        zero_hit_rate=summary.zero_hit_rate,
        error_rate=error_rate,
    )


async def build_slo_snapshot(*, tenant_id: str | None) -> dict[str, Any]:
    """
    Build an SLO snapshot for 1h + 24h windows.

    Output is PII-safe: numbers only (no raw query/doc content).
    """
    windows: list[SloWindowSnapshot] = []
    for w in (60, 24 * 60):
        snap: SloWindowSnapshot | None = None
        try:
            snap = await _build_window_from_prometheus(window_minutes=w)
        except Exception:
            snap = None
        if snap is None:
            snap = _build_window_from_metrics_jsonl(tenant_id=tenant_id, window_minutes=w)
        windows.append(snap)

    return {
        "schema": SLO_SNAPSHOT_SCHEMA_V1,
        "generated_at": _now_utc(),
        "windows": [w.__dict__ for w in windows],
    }


__all__ = ["SLO_SNAPSHOT_SCHEMA_V1", "build_slo_snapshot"]

