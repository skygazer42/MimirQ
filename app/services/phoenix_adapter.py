
from typing import Any

from app.services.rag_metrics_dashboard import RagTraceBundle


def _first_event(records: list[dict[str, Any]], event: str) -> dict[str, Any] | None:
    for record in records or []:
        if str(record.get("event") or "") == event:
            return record
    return None


def build_phoenix_trace_payload(bundle: RagTraceBundle) -> dict[str, Any]:
    records = list(getattr(bundle, "records", []) or [])
    trace = _first_event(records, "rag_trace") or {}
    done = _first_event(records, "rag_done") or {}
    retrieval = trace.get("retrieval") if isinstance(trace.get("retrieval"), dict) else {}
    metrics = done.get("metrics") if isinstance(done.get("metrics"), dict) else {}

    spans: list[dict[str, Any]] = []
    if retrieval:
        spans.append(
            {
                "name": "retrieval",
                "start_time_ms": trace.get("ts_ms"),
                "end_time_ms": None,
                "attributes": {
                    "retrieval.mode": str(retrieval.get("mode") or ""),
                    "retrieval.profile": str(retrieval.get("profile") or ""),
                    "retrieval.top_k": int(retrieval.get("top_k") or 0),
                    "retrieval.elapsed_sec": float(retrieval.get("elapsed_sec") or 0.0),
                    "retrieval.citations_count": int(trace.get("citations_count") or 0),
                },
            }
        )
    if metrics or done:
        spans.append(
            {
                "name": "generation",
                "start_time_ms": done.get("ts_ms"),
                "end_time_ms": None,
                "attributes": {
                    "generation.route": str(done.get("route") or ""),
                    "generation.model_used": str(done.get("model_used") or ""),
                    "generation.elapsed_sec": float(metrics.get("generation_elapsed_sec") or 0.0),
                    "generation.context_tokens": int(metrics.get("context_tokens") or 0),
                },
            }
        )

    return {
        "schema": "mimirq.phoenix_adapter.v1",
        "request_id": str(getattr(bundle, "request_id", "") or ""),
        "spans": spans,
    }


__all__ = ["build_phoenix_trace_payload"]
