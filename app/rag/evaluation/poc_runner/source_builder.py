from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.rag.core.logging import get_logger
from app.rag.evaluation.poc_runner.telemetry import feedback_polarity_from_score


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


def _safe_str(value: Any, *, max_len: int = 255) -> str | None:
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


def _assistant_request_id(message: dict[str, Any]) -> str | None:
    meta = _coerce_mapping(message.get("message_metadata"))
    return _safe_str(meta.get("request_id"))


def _feedback_request_id(feedback: dict[str, Any]) -> str | None:
    extra = _coerce_mapping(feedback.get("extra"))
    return _safe_str(extra.get("retrieval_trace_request_id") or feedback.get("request_id"))


def build_dataset_analysis_sources(
    *,
    traces: list[dict[str, Any]],
    feedback_rows: list[dict[str, Any]] | None = None,
    conversations: list[dict[str, Any]] | None = None,
    messages: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    conversation_by_id = {
        cid: row
        for row in (_coerce_mapping(item) for item in (conversations or []))
        if (cid := _safe_str(row.get("id"))) is not None
    }

    assistant_by_request_id: dict[str, dict[str, Any]] = {}
    assistant_by_id: dict[str, dict[str, Any]] = {}
    assistants_by_conversation: dict[str, list[dict[str, Any]]] = {}
    users_by_conversation: dict[str, list[dict[str, Any]]] = {}
    for raw in messages or []:
        row = _coerce_mapping(raw)
        conversation_id = _safe_str(row.get("conversation_id"))
        if conversation_id is None:
            continue
        role = str(row.get("role") or "").strip().lower()
        if role == "assistant":
            assistants_by_conversation.setdefault(conversation_id, []).append(row)
            message_id = _safe_str(row.get("id"))
            if message_id is not None:
                assistant_by_id[message_id] = row
            request_id = _assistant_request_id(row)
            if request_id is not None:
                assistant_by_request_id[request_id] = row
        elif role == "user":
            users_by_conversation.setdefault(conversation_id, []).append(row)

    for group in assistants_by_conversation.values():
        group.sort(key=lambda item: _coerce_datetime(item.get("created_at")) or datetime.min.replace(tzinfo=UTC))
    for group in users_by_conversation.values():
        group.sort(key=lambda item: _coerce_datetime(item.get("created_at")) or datetime.min.replace(tzinfo=UTC))

    feedback_by_request_id: dict[str, dict[str, Any]] = {}
    feedback_by_message_id: dict[str, dict[str, Any]] = {}
    feedback_by_conversation_id: dict[str, list[dict[str, Any]]] = {}
    for raw in feedback_rows or []:
        row = _coerce_mapping(raw)
        request_id = _feedback_request_id(row)
        if request_id is not None and request_id not in feedback_by_request_id:
            feedback_by_request_id[request_id] = row
        message_id = _safe_str(row.get("message_id"))
        if message_id is not None and message_id not in feedback_by_message_id:
            feedback_by_message_id[message_id] = row
        conversation_id = _safe_str(row.get("conversation_id"))
        if conversation_id is not None:
            feedback_by_conversation_id.setdefault(conversation_id, []).append(row)

    rows: list[dict[str, Any]] = []
    feedback_interactions = 0
    attributable_feedback_interactions = 0

    for raw_trace in traces or []:
        trace = _coerce_mapping(raw_trace)
        request_id = _safe_str(trace.get("request_id"))
        conversation_id = _safe_str(trace.get("conversation_id"))
        conversation = conversation_by_id.get(conversation_id or "", {})

        assistant_match: str | None = None
        assistant_message: dict[str, Any] | None = None
        if request_id and request_id in assistant_by_request_id:
            assistant_message = assistant_by_request_id[request_id]
            assistant_match = "request_id"
        elif conversation_id:
            candidates = assistants_by_conversation.get(conversation_id) or []
            if len(candidates) == 1:
                assistant_message = candidates[0]
                assistant_match = "conversation_id"

        feedback_match: str | None = None
        feedback = None
        if request_id and request_id in feedback_by_request_id:
            feedback = feedback_by_request_id[request_id]
            feedback_match = "request_id"
        elif assistant_message is not None:
            assistant_id = _safe_str(assistant_message.get("id"))
            if assistant_id and assistant_id in feedback_by_message_id:
                feedback = feedback_by_message_id[assistant_id]
                feedback_match = "message_id"
        elif conversation_id:
            candidates = feedback_by_conversation_id.get(conversation_id) or []
            if len(candidates) == 1:
                feedback = candidates[0]
                feedback_match = "conversation_id"

        if assistant_message is None and feedback is not None:
            assistant_id = _safe_str(_coerce_mapping(feedback).get("message_id"))
            if assistant_id and assistant_id in assistant_by_id:
                assistant_message = assistant_by_id[assistant_id]
                assistant_match = "message_id"

        user_message = None
        if conversation_id:
            candidates = users_by_conversation.get(conversation_id) or []
            if candidates:
                if assistant_message is not None:
                    assistant_dt = _coerce_datetime(assistant_message.get("created_at"))
                    before = [
                        item
                        for item in candidates
                        if assistant_dt is None
                        or (_coerce_datetime(item.get("created_at")) or datetime.min.replace(tzinfo=UTC)) <= assistant_dt
                    ]
                    user_message = before[-1] if before else candidates[-1]
                else:
                    user_message = candidates[-1]

        row = {
            "trace": trace,
            "conversation": conversation,
            "assistant_message": assistant_message or {},
            "user_message": user_message or {},
            "feedback": feedback or {},
            "linkage": {
                "assistant_match": assistant_match,
                "feedback_match": feedback_match,
            },
        }
        rows.append(row)

        if feedback:
            feedback_interactions += 1
            polarity = feedback_polarity_from_score(_coerce_mapping(feedback).get("rating"))
            if polarity == "negative":
                attributable_feedback_interactions += 1

    return {
        "rows": rows,
        "counts": {
            "all_interactions": len(rows),
            "feedback_interactions": feedback_interactions,
            "attributable_feedback_interactions": attributable_feedback_interactions,
        },
    }
