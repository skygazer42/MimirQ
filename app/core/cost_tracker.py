from __future__ import annotations

from collections import defaultdict
from typing import Any

from prometheus_client import Counter

from app.services.metrics_logger import log_metrics

COST_EVENT_SCHEMA_V1 = "mimirq.cost_event.v1"
COST_SUMMARY_SCHEMA_V1 = "mimirq.cost_summary.v1"

COST_EVENTS_TOTAL = Counter(
    "rag_cost_events_total",
    "Total counted RAG cost events.",
    ["provider", "model", "tenant_id", "stage"],
)
COST_TOKENS_TOTAL = Counter(
    "rag_cost_tokens_total",
    "Total counted RAG tokens.",
    ["provider", "model", "tenant_id", "stage"],
)
COST_USD_TOTAL = Counter(
    "rag_cost_usd_total",
    "Total counted RAG cost in USD.",
    ["provider", "model", "tenant_id", "stage"],
)


def _to_int(value: Any) -> int:
    try:
        if value is None:
            return 0
        if isinstance(value, bool):
            return 0
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _to_float(value: Any) -> float:
    try:
        if value is None or isinstance(value, bool):
            return 0.0
        num = float(value)
        if num != num:
            return 0.0
        return max(0.0, num)
    except (TypeError, ValueError):
        return 0.0


def _clean_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def build_cost_event(
    *,
    provider: str,
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cost_usd: float = 0.0,
    tenant_id: str | None = None,
    dataset_id: str | None = None,
    request_id: str | None = None,
    stage: str | None = None,
) -> dict[str, Any]:
    input_t = _to_int(input_tokens)
    output_t = _to_int(output_tokens)
    return {
        "schema": COST_EVENT_SCHEMA_V1,
        "provider": _clean_text(provider),
        "model": _clean_text(model),
        "input_tokens": input_t,
        "output_tokens": output_t,
        "total_tokens": int(input_t + output_t),
        "cost_usd": round(_to_float(cost_usd), 6),
        "tenant_id": _clean_text(tenant_id),
        "dataset_id": _clean_text(dataset_id),
        "request_id": _clean_text(request_id),
        "stage": _clean_text(stage),
    }


def summarize_cost_events(events: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [dict(item or {}) for item in list(events or [])]
    by_provider: dict[str, dict[str, Any]] = defaultdict(lambda: {"events": 0, "total_tokens": 0, "total_cost_usd": 0.0})
    by_tenant: dict[str, dict[str, Any]] = defaultdict(lambda: {"events": 0, "total_tokens": 0, "total_cost_usd": 0.0})

    total_tokens = 0
    total_cost = 0.0
    for row in rows:
        provider = _clean_text(row.get("provider")) or "unknown"
        tenant = _clean_text(row.get("tenant_id")) or "unknown"
        event_tokens = _to_int(row.get("total_tokens"))
        if event_tokens <= 0:
            event_tokens = _to_int(row.get("input_tokens")) + _to_int(row.get("output_tokens"))
        event_cost = _to_float(row.get("cost_usd"))

        total_tokens += event_tokens
        total_cost += event_cost

        by_provider[provider]["events"] += 1
        by_provider[provider]["total_tokens"] += event_tokens
        by_provider[provider]["total_cost_usd"] += event_cost

        by_tenant[tenant]["events"] += 1
        by_tenant[tenant]["total_tokens"] += event_tokens
        by_tenant[tenant]["total_cost_usd"] += event_cost

    def _normalize_bucket(bucket: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for key in sorted(bucket.keys()):
            item = bucket[key]
            out[key] = {
                "events": int(item["events"]),
                "total_tokens": int(item["total_tokens"]),
                "total_cost_usd": round(float(item["total_cost_usd"]), 6),
            }
        return out

    return {
        "schema": COST_SUMMARY_SCHEMA_V1,
        "events": int(len(rows)),
        "total_tokens": int(total_tokens),
        "total_cost_usd": round(float(total_cost), 6),
        "by_provider": _normalize_bucket(by_provider),
        "by_tenant": _normalize_bucket(by_tenant),
    }


def record_cost_event(
    *,
    provider: str,
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cost_usd: float = 0.0,
    tenant_id: str | None = None,
    dataset_id: str | None = None,
    request_id: str | None = None,
    stage: str | None = None,
) -> dict[str, Any]:
    event = build_cost_event(
        provider=provider,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=cost_usd,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        request_id=request_id,
        stage=stage,
    )
    labels = {
        "provider": str(event.get("provider") or "unknown"),
        "model": str(event.get("model") or "unknown"),
        "tenant_id": str(event.get("tenant_id") or "unknown"),
        "stage": str(event.get("stage") or "unknown"),
    }
    COST_EVENTS_TOTAL.labels(**labels).inc()
    COST_TOKENS_TOTAL.labels(**labels).inc(float(event.get("total_tokens") or 0.0))
    COST_USD_TOTAL.labels(**labels).inc(float(event.get("cost_usd") or 0.0))
    log_metrics({"event": "cost_event", **{k: v for k, v in event.items() if k != "schema"}})
    return event


__all__ = [
    "COST_EVENT_SCHEMA_V1",
    "COST_SUMMARY_SCHEMA_V1",
    "COST_EVENTS_TOTAL",
    "COST_TOKENS_TOTAL",
    "COST_USD_TOTAL",
    "build_cost_event",
    "record_cost_event",
    "summarize_cost_events",
]
