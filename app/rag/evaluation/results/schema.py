from __future__ import annotations

from typing import Any

EVAL_RESULT_SCHEMA_V1 = "mimirq.eval.result.v1"


def normalize_eval_result_row(row: dict[str, Any]) -> dict[str, Any]:
    payload = dict(row or {})
    return {
        "schema_version": EVAL_RESULT_SCHEMA_V1,
        "sample_id": str(payload.get("sample_id") or ""),
        "route_id": str(payload.get("route_id") or ""),
        "query_type": str(payload.get("query_type") or ""),
        "source_type": str(payload.get("source_type") or ""),
        "expected_route": payload.get("expected_route"),
        "actual_route": payload.get("actual_route"),
        "answer": dict(payload.get("answer") or {}),
        "citations": list(payload.get("citations") or []),
        "latency_ms": payload.get("latency_ms"),
        "token_cost": payload.get("token_cost"),
        "route_config": dict(payload.get("route_config") or {}),
        "evaluators": dict(payload.get("evaluators") or {}),
        "agentic_iterations": payload.get("agentic_iterations"),
        "agentic_latency_ms": payload.get("agentic_latency_ms"),
        "agentic_token_cost": payload.get("agentic_token_cost"),
        "agentic_status": payload.get("agentic_status"),
        "extensions": dict(payload.get("extensions") or {}),
    }


__all__ = [
    "EVAL_RESULT_SCHEMA_V1",
    "normalize_eval_result_row",
]
