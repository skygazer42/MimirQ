from __future__ import annotations

from typing import Any

_SCHEMA = "mimirq.poc.latency_decomposer.v1"


def _to_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except Exception:
        return None


def _to_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _decompose_row(row: dict[str, Any]) -> dict[str, Any]:
    total_ms = _to_int(row.get("latency_total_ms")) or 0
    retrieval_ms = int(round((_to_float(row.get("retrieval_elapsed_sec")) or 0.0) * 1000.0))
    generation_ms = int(round((_to_float(row.get("generation_elapsed_sec")) or 0.0) * 1000.0))
    active_inference_ms = retrieval_ms + generation_ms
    wait_in_queue_ms = max(0, int(total_ms - active_inference_ms))

    prompt_tokens = max(0, _to_int(row.get("prompt_tokens")) or 0)
    completion_tokens = max(0, _to_int(row.get("completion_tokens")) or _to_int(row.get("answer_tokens")) or 0)
    if generation_ms > 0 and (prompt_tokens + completion_tokens) > 0:
        token_total = max(1, prompt_tokens + completion_tokens)
        model_prefill_ms = int(round(generation_ms * (prompt_tokens / token_total)))
        model_decode_ms = max(0, generation_ms - model_prefill_ms)
    elif generation_ms > 0:
        model_prefill_ms = int(round(generation_ms * 0.35))
        model_decode_ms = max(0, generation_ms - model_prefill_ms)
    else:
        model_prefill_ms = 0
        model_decode_ms = 0

    if wait_in_queue_ms >= max(1000, active_inference_ms):
        bottleneck = "concurrency_issue"
    elif active_inference_ms >= max(wait_in_queue_ms * 2, 3000):
        bottleneck = "hardware_or_model_issue"
    else:
        bottleneck = "balanced"

    return {
        "interaction_id": str(row.get("interaction_id") or ""),
        "latency_total_ms": int(total_ms),
        "retrieval_ms": int(retrieval_ms),
        "generation_ms": int(generation_ms),
        "active_inference_ms": int(active_inference_ms),
        "wait_in_queue_ms": int(wait_in_queue_ms),
        "model_prefill_ms": int(model_prefill_ms),
        "model_decode_ms": int(model_decode_ms),
        "bottleneck": bottleneck,
    }


def decompose_latency_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    out_rows = [_decompose_row(dict(row or {})) for row in (rows or []) if isinstance(row, dict)]
    total = max(1, len(out_rows))
    summary = {
        "avg_wait_in_queue_ms": round(sum(row["wait_in_queue_ms"] for row in out_rows) / total, 2) if out_rows else 0.0,
        "avg_active_inference_ms": round(sum(row["active_inference_ms"] for row in out_rows) / total, 2) if out_rows else 0.0,
        "concurrency_issue_count": sum(1 for row in out_rows if row["bottleneck"] == "concurrency_issue"),
        "hardware_or_model_issue_count": sum(1 for row in out_rows if row["bottleneck"] == "hardware_or_model_issue"),
        "balanced_count": sum(1 for row in out_rows if row["bottleneck"] == "balanced"),
    }
    return {
        "schema": _SCHEMA,
        "rows": out_rows,
        "summary": summary,
    }
