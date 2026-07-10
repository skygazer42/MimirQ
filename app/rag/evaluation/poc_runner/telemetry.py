
from datetime import UTC, datetime
from typing import Any

from app.rag.core.logging import get_logger

POC_TELEMETRY_SCHEMA_V1 = "mimirq.poc.telemetry.v1"


def _coerce_mapping(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "model_dump"):
        try:
            return dict(value.model_dump(mode="json"))
        except Exception:
            return {}
    out: dict[str, Any] = {}
    for key in dir(value):
        if key.startswith("_"):
            continue
        try:
            current = getattr(value, key)
        except Exception:
            get_logger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
            continue
        if callable(current):
            continue
        out[key] = current
    return out


def _safe_str(value: Any, *, max_len: int = 2_000) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return text[: max(1, int(max_len or 1))]


def _coerce_datetime(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except Exception:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _coerce_iso(value: Any) -> str | None:
    parsed = _coerce_datetime(value)
    return parsed.isoformat() if parsed is not None else None


def _coerce_int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except Exception:
        return None


def _coerce_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def feedback_polarity_from_score(score: Any) -> str:
    numeric = _coerce_int(score)
    if numeric is None:
        return "none"
    if numeric <= 2:
        return "negative"
    if numeric >= 4:
        return "positive"
    return "neutral"


def _extract_trace(source: dict[str, Any]) -> dict[str, Any]:
    trace = _coerce_mapping(source.get("trace"))
    if trace:
        return trace
    extra = _coerce_mapping(source.get("extra"))
    return _coerce_mapping(extra.get("retrieval_trace"))


def _dedupe_filenames(citations: Any) -> list[str]:
    if not isinstance(citations, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for item in citations:
        payload = _coerce_mapping(item)
        name = _safe_str(
            payload.get("source")
            or payload.get("filename")
            or payload.get("document_name")
            or payload.get("document_id"),
            max_len=255,
        )
        if name is None:
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(name)
    return out


def _resolve_latency_total_ms(trace: dict[str, Any]) -> int | None:
    retrieval = _coerce_mapping(trace.get("retrieval"))
    direct_ms = _coerce_int(retrieval.get("latency_total_ms"))
    if direct_ms is not None:
        return max(0, direct_ms)
    elapsed_sec = retrieval.get("elapsed_sec")
    try:
        if elapsed_sec is None:
            return None
        return max(0, int(round(float(elapsed_sec) * 1000.0)))
    except Exception:
        return None


def build_poc_interaction_row(source: dict[str, Any]) -> dict[str, Any]:
    source_map = _coerce_mapping(source)
    trace = _extract_trace(source_map)
    conversation = _coerce_mapping(source_map.get("conversation"))
    user_message = _coerce_mapping(source_map.get("user_message"))
    assistant_message = _coerce_mapping(source_map.get("assistant_message"))
    feedback = _coerce_mapping(source_map.get("feedback"))
    if not feedback and any(key in source_map for key in ("rating", "reason", "tags", "extra")):
        feedback = source_map

    assistant_meta = _coerce_mapping(assistant_message.get("message_metadata"))
    feedback_extra = _coerce_mapping(feedback.get("extra"))

    total_elapsed_sec = _coerce_float(assistant_meta.get("elapsed_sec"))
    retrieval_elapsed_sec = _coerce_float(assistant_meta.get("retrieval_elapsed_sec"))
    generation_elapsed_sec = _coerce_float(assistant_meta.get("generation_elapsed_sec"))
    rewrite_elapsed_sec = _coerce_float(assistant_meta.get("rewrite_elapsed_sec"))
    hyde_elapsed_sec = _coerce_float(assistant_meta.get("hyde_elapsed_sec"))
    decompose_elapsed_sec = _coerce_float(assistant_meta.get("decompose_elapsed_sec"))
    prompt_tokens = _coerce_int(
        assistant_meta.get("prompt_tokens")
        if assistant_meta.get("prompt_tokens") is not None
        else assistant_meta.get("cost_llm_prompt_tokens")
    )
    completion_tokens = _coerce_int(
        assistant_meta.get("completion_tokens")
        if assistant_meta.get("completion_tokens") is not None
        else assistant_meta.get("cost_llm_completion_tokens")
    )
    answer_tokens = _coerce_int(assistant_meta.get("answer_tokens") or completion_tokens or assistant_message.get("token_count"))

    request_id = _safe_str(
        trace.get("request_id")
        or assistant_meta.get("request_id")
        or feedback_extra.get("retrieval_trace_request_id"),
        max_len=255,
    )
    conversation_id = _safe_str(
        trace.get("conversation_id")
        or conversation.get("id")
        or assistant_message.get("conversation_id")
        or user_message.get("conversation_id")
        or feedback.get("conversation_id"),
        max_len=255,
    )
    dataset_id = _safe_str(
        conversation.get("dataset_id")
        or assistant_meta.get("dataset_id")
        or feedback_extra.get("dataset_id")
        or trace.get("dataset_id"),
        max_len=255,
    )
    created_at = (
        _coerce_iso(feedback.get("created_at"))
        or _coerce_iso(assistant_message.get("created_at"))
        or _coerce_iso(user_message.get("created_at"))
    )
    feedback_score = _coerce_int(feedback.get("rating"))
    feedback_polarity = feedback_polarity_from_score(feedback_score)
    citations = trace.get("citations")
    if not isinstance(citations, list) or not citations:
        citations = assistant_message.get("citations")

    interaction_id = (
        request_id
        or _safe_str(assistant_message.get("id"), max_len=255)
        or _safe_str(feedback.get("id"), max_len=255)
        or conversation_id
        or _safe_str(user_message.get("id"), max_len=255)
        or "unknown"
    )

    return {
        "schema": POC_TELEMETRY_SCHEMA_V1,
        "interaction_id": interaction_id,
        "request_id": request_id,
        "feedback_id": _safe_str(feedback.get("id"), max_len=255),
        "conversation_id": conversation_id,
        "dataset_id": dataset_id,
        "user_message_id": _safe_str(user_message.get("id"), max_len=255),
        "assistant_message_id": _safe_str(assistant_message.get("id"), max_len=255),
        "original_query": _safe_str(user_message.get("content")),
        "llm_response": _safe_str(assistant_message.get("content")),
        "final_context_filenames": _dedupe_filenames(citations),
        "citation_count": len(citations) if isinstance(citations, list) else 0,
        "feedback_score": feedback_score,
        "feedback_comment": _safe_str(feedback.get("reason")),
        "has_feedback": bool(feedback),
        "feedback_polarity": feedback_polarity,
        "attributable_feedback_eligible": feedback_polarity == "negative",
        "latency_total_ms": (
            int(round(total_elapsed_sec * 1000.0))
            if total_elapsed_sec is not None
            else _resolve_latency_total_ms(trace)
        ),
        "latency_total_sec": round(float(total_elapsed_sec), 4) if total_elapsed_sec is not None else None,
        "retrieval_elapsed_sec": round(float(retrieval_elapsed_sec), 4) if retrieval_elapsed_sec is not None else None,
        "generation_elapsed_sec": round(float(generation_elapsed_sec), 4) if generation_elapsed_sec is not None else None,
        "rewrite_elapsed_sec": round(float(rewrite_elapsed_sec), 4) if rewrite_elapsed_sec is not None else None,
        "hyde_elapsed_sec": round(float(hyde_elapsed_sec), 4) if hyde_elapsed_sec is not None else None,
        "decompose_elapsed_sec": round(float(decompose_elapsed_sec), 4) if decompose_elapsed_sec is not None else None,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "answer_tokens": answer_tokens,
        "created_at": created_at,
        "trace_ts_ms": _coerce_int(trace.get("ts_ms")),
        "retrieval_trace_request_id": _safe_str(feedback_extra.get("retrieval_trace_request_id"), max_len=255),
    }


def build_poc_interaction_rows(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for item in items or []:
        out.append(build_poc_interaction_row(item))
    return out
