"""Normalize evidence references and materialize feedback cases without model tooling."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.models.chat import Conversation, Message
from app.models.feedback import MessageFeedback


def _safe_uuid_text(value: Any) -> str | None:
    if value is None:
        return None
    try:
        text = str(value).strip()
        if not text:
            return None
        return str(UUID(text))
    except Exception:
        return None


def _safe_text(value: Any, *, max_len: int = 2000) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return text[: max(1, int(max_len or 1))]


def _safe_int(value: Any, *, min_value: int | None = None) -> int | None:
    try:
        if value is None:
            return None
        out = int(value)
    except Exception:
        return None
    if min_value is not None and out < min_value:
        return None
    return out


def _normalize_tags(values: Sequence[Any] | None, *, prefixes: Sequence[str] | None = None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in list((prefixes if prefixes is not None else [])) + list((values if values is not None else [])):
        text = str(raw or "").strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(text[:64])
        if len(out) >= 30:
            break
    return out


def _normalized_reference_source_identity(item: dict[str, Any]) -> tuple[str, str] | None:
    document_id = _safe_uuid_text(item.get("document_id"))
    chunk_id = _safe_uuid_text(item.get("chunk_id"))
    if not document_id or not chunk_id:
        return None
    return document_id, chunk_id


def _normalized_reference_source_payload(item: dict[str, Any], *, document_id: str, chunk_id: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "document_id": document_id,
        "chunk_id": chunk_id,
    }
    for field_name, min_value in (
        ("page_number", 1),
        ("start_char", 0),
        ("end_char", 0),
        ("chunk_index", 0),
    ):
        value_int = _safe_int(item.get(field_name), min_value=min_value)
        if value_int is not None:
            payload[field_name] = value_int
    for field_name, max_len in (
        ("doc_pipeline_key", 128),
        ("pipeline_hash", 128),
        ("quote", 2000),
        ("label", 128),
    ):
        text = _safe_text(item.get(field_name), max_len=max_len)
        if text:
            payload[field_name] = text
    return payload


def normalize_reference_sources(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        identity = _normalized_reference_source_identity(item)
        if identity is None:
            continue
        key = identity
        if key in seen:
            continue
        seen.add(key)
        out.append(_normalized_reference_source_payload(item, document_id=key[0], chunk_id=key[1]))
        if len(out) >= 100:
            break
    return out


@dataclass(frozen=True)
class FeedbackCaseMaterialization:
    feedback_id: str
    dataset_id: str | None
    question: str
    expected_answer: str | None
    reference_sources: list[dict[str, Any]]
    tags: list[str]
    extra: dict[str, Any]


def materialize_feedback_case(
    *,
    feedback: MessageFeedback,
    assistant: Message,
    conversation: Conversation,
    user_message: Message | None,
    trace_payload: dict[str, Any] | None = None,
) -> FeedbackCaseMaterialization:
    meta = assistant.message_metadata if isinstance(assistant.message_metadata, dict) else {}
    dataset_id = _safe_uuid_text(meta.get("dataset_id")) or _safe_uuid_text(conversation.dataset_id)
    request_id = str(meta.get("request_id") or "").strip()

    question = str(getattr(user_message, "content", "") or "").strip() or "(missing user question)"
    reference_sources = normalize_reference_sources(assistant.citations)
    if not reference_sources and isinstance(trace_payload, dict):
        reference_sources = normalize_reference_sources(trace_payload.get("citations"))

    tags = _normalize_tags(feedback.tags)
    extra = dict(feedback.extra or {})
    extra.setdefault("source", "feedback")
    extra.setdefault("feedback_id", str(feedback.id))
    extra.setdefault("message_id", str(feedback.message_id))
    extra.setdefault("rating", int(feedback.rating or 0))
    if request_id:
        extra["retrieval_trace_request_id"] = request_id
    if isinstance(trace_payload, dict) and trace_payload:
        extra["retrieval_trace"] = dict(trace_payload)

    return FeedbackCaseMaterialization(
        feedback_id=str(feedback.id),
        dataset_id=dataset_id,
        question=question,
        expected_answer=_safe_text(feedback.expected_answer, max_len=20_000),
        reference_sources=reference_sources,
        tags=tags,
        extra=extra,
    )
