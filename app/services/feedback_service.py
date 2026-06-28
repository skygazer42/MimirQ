from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Callable
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.chat import Conversation, Message
from app.models.feedback import MessageFeedback
from app.rag.feedback_loop.candidates import build_feedback_loop_candidates as build_feedback_loop_candidate_payload
from app.rag.industry_rules.schema import IndustryRuleset
from app.services.rag_trace_service import list_rag_traces
from app.rag.core.logging import get_logger


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


def _find_trace_by_request_id(
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    request_id: str,
    list_rag_traces_fn: Callable[..., Any] = list_rag_traces,
) -> dict[str, Any] | None:
    rid = str(request_id or "").strip()
    if not rid:
        return None
    try:
        traces = list_rag_traces_fn(
            tenant_id=str(tenant_id),
            conversation_id=str(conversation_id),
            limit=100,
            window_minutes=7 * 24 * 60,
            max_bytes=10_000_000,
        )
    except Exception:
        return None
    for item in (getattr(traces, "items", []) or []):
        if str(getattr(item, "request_id", "") or "") != rid:
            continue
        return _coerce_mapping(item)
    return None


def _extract_rag_config_snapshot(trace_payload: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(trace_payload, dict):
        return {}
    retrieval = trace_payload.get("retrieval")
    if not isinstance(retrieval, dict):
        return {}
    return dict(retrieval)


def _augment_feedback_extra_with_snapshots(
    *,
    extra: dict[str, Any] | None,
    trace_payload: dict[str, Any] | None,
    request_id: str,
    dataset_id: UUID | None,
) -> dict[str, Any]:
    payload = dict(extra or {})
    if dataset_id is not None:
        payload["dataset_id"] = str(dataset_id)
    if request_id:
        payload["retrieval_trace_request_id"] = str(request_id)
    if isinstance(trace_payload, dict) and trace_payload:
        payload["retrieval_trace"] = dict(trace_payload)
        rag_config_snapshot = _extract_rag_config_snapshot(trace_payload)
        if rag_config_snapshot:
            payload["rag_config_snapshot"] = rag_config_snapshot
    return payload


def _feedback_sort_key(row: MessageFeedback) -> datetime:
    updated_at = getattr(row, "updated_at", None)
    if isinstance(updated_at, datetime):
        return updated_at if updated_at.tzinfo is not None else updated_at.replace(tzinfo=UTC)
    created_at = getattr(row, "created_at", None)
    if isinstance(created_at, datetime):
        return created_at if created_at.tzinfo is not None else created_at.replace(tzinfo=UTC)
    return datetime.min.replace(tzinfo=UTC)


def _safe_text(value: Any, *, max_len: int = 4000) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    return text[: max(0, int(max_len or 0))]


def _feedback_loop_reference_sources(citations: Any) -> list[dict[str, Any]]:
    if not isinstance(citations, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in citations:
        if not isinstance(item, dict):
            continue
        doc_id = _safe_text(item.get("document_id"), max_len=200)
        chunk_id = _safe_text(item.get("chunk_id"), max_len=200)
        if not chunk_id:
            continue
        key = (doc_id, chunk_id)
        if key in seen:
            continue
        seen.add(key)
        row: dict[str, Any] = {"chunk_id": chunk_id}
        if doc_id:
            row["document_id"] = doc_id
        for key_name in ("page_number", "start_char", "end_char", "chunk_index", "pipeline_hash", "quote", "label"):
            if key_name in item and item.get(key_name) is not None:
                row[key_name] = item.get(key_name)
        out.append(row)
        if len(out) >= 100:
            break
    return out


def _previous_user_question(
    *,
    messages: list[Message],
    conversation_id: UUID,
    assistant_created_at: datetime | None,
) -> str:
    candidates: list[Message] = []
    for msg in messages:
        if getattr(msg, "conversation_id", None) != conversation_id:
            continue
        if str(getattr(msg, "role", "") or "").lower() != "user":
            continue
        created_at = getattr(msg, "created_at", None)
        if isinstance(assistant_created_at, datetime) and isinstance(created_at, datetime) and created_at > assistant_created_at:
            continue
        candidates.append(msg)
    candidates.sort(key=lambda item: getattr(item, "created_at", None) or datetime.min.replace(tzinfo=UTC), reverse=True)
    return _safe_text(getattr(candidates[0], "content", "") if candidates else "", max_len=4000)


class FeedbackService:
    @staticmethod
    def _build_feedback_query(
        *,
        db: Session,
        tenant_id: UUID,
        conversation_id: UUID | None,
        message_id: UUID | None,
        min_rating: int | None,
        max_rating: int | None,
    ):
        query = db.query(MessageFeedback).filter(MessageFeedback.tenant_id == tenant_id)
        if conversation_id:
            query = query.filter(MessageFeedback.conversation_id == conversation_id)
        if message_id:
            query = query.filter(MessageFeedback.message_id == message_id)
        if min_rating is not None:
            query = query.filter(MessageFeedback.rating >= int(min_rating))
        if max_rating is not None:
            query = query.filter(MessageFeedback.rating <= int(max_rating))
        return query

    @staticmethod
    def _ensure_member(
        *,
        db: Session,
        tenant_id: UUID,
        account_id: str,
        ensure_member_fn: Callable[[Session, UUID, str], Any] | None,
    ) -> None:
        if callable(ensure_member_fn):
            ensure_member_fn(db, tenant_id, account_id)

    @staticmethod
    def upsert_message_feedback(
        *,
        db: Session,
        tenant_id: UUID,
        account_id: str,
        message_id: UUID,
        rating: int,
        reason: str | None,
        tags: list[str] | None,
        expected_answer: str | None,
        extra: dict[str, Any] | None,
        ensure_member_fn: Callable[[Session, UUID, str], Any] | None = None,
        list_rag_traces_fn: Callable[..., Any] = list_rag_traces,
    ) -> MessageFeedback:
        FeedbackService._ensure_member(
            db=db,
            tenant_id=tenant_id,
            account_id=account_id,
            ensure_member_fn=ensure_member_fn,
        )

        msg = db.query(Message).filter(Message.id == message_id, Message.tenant_id == tenant_id).first()
        if not msg:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")
        if (getattr(msg, "role", "") or "").lower() != "assistant":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Only assistant messages can be rated")

        conv = db.query(Conversation).filter(Conversation.id == msg.conversation_id, Conversation.tenant_id == tenant_id).first()
        meta = msg.message_metadata if isinstance(getattr(msg, "message_metadata", None), dict) else {}
        request_id = str(meta.get("request_id") or "").strip() if isinstance(meta, dict) else ""

        dataset_id: UUID | None = None
        raw_dataset_id = meta.get("dataset_id") if isinstance(meta, dict) else None
        if isinstance(raw_dataset_id, str) and raw_dataset_id.strip():
            try:
                dataset_id = UUID(raw_dataset_id.strip())
            except Exception:
                dataset_id = None
        if dataset_id is None and conv is not None:
            dataset_id = getattr(conv, "dataset_id", None)

        trace_payload = None
        if conv is not None and request_id:
            trace_payload = _find_trace_by_request_id(
                tenant_id=tenant_id,
                conversation_id=conv.id,
                request_id=request_id,
                list_rag_traces_fn=list_rag_traces_fn,
            )

        extra_payload = _augment_feedback_extra_with_snapshots(
            extra=extra if isinstance(extra, dict) else {},
            trace_payload=trace_payload,
            request_id=request_id,
            dataset_id=dataset_id,
        )

        row = (
            db.query(MessageFeedback)
            .filter(
                MessageFeedback.tenant_id == tenant_id,
                MessageFeedback.message_id == msg.id,
                MessageFeedback.account_id == account_id,
            )
            .first()
        )
        normalized_tags = [str(item) for item in (tags or [])]
        if row:
            row.rating = int(rating)
            row.reason = reason
            row.tags = normalized_tags
            row.expected_answer = expected_answer
            row.extra = extra_payload
            db.commit()
            db.refresh(row)
            return row

        row = MessageFeedback(
            tenant_id=tenant_id,
            conversation_id=msg.conversation_id,
            message_id=msg.id,
            account_id=account_id,
            rating=int(rating),
            reason=reason,
            tags=normalized_tags,
            expected_answer=expected_answer,
            extra=extra_payload,
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return row

    @staticmethod
    def list_message_feedback(
        *,
        db: Session,
        tenant_id: UUID,
        account_id: str,
        conversation_id: UUID | None,
        message_id: UUID | None,
        min_rating: int | None,
        max_rating: int | None,
        skip: int,
        limit: int,
        ensure_member_fn: Callable[[Session, UUID, str], Any] | None = None,
    ) -> dict[str, Any]:
        FeedbackService._ensure_member(
            db=db,
            tenant_id=tenant_id,
            account_id=account_id,
            ensure_member_fn=ensure_member_fn,
        )
        rows = list(
            FeedbackService._build_feedback_query(
                db=db,
                tenant_id=tenant_id,
                conversation_id=conversation_id,
                message_id=message_id,
                min_rating=min_rating,
                max_rating=max_rating,
            ).all()
        )
        rows.sort(key=_feedback_sort_key, reverse=True)
        total = len(rows)
        start = max(0, int(skip or 0))
        size = max(1, int(limit or 1))
        return {"total": total, "items": rows[start : start + size]}

    @staticmethod
    def list_message_feedback_enriched(
        *,
        db: Session,
        tenant_id: UUID,
        account_id: str,
        conversation_id: UUID | None,
        message_id: UUID | None,
        min_rating: int | None,
        max_rating: int | None,
        skip: int,
        limit: int,
        ensure_member_fn: Callable[[Session, UUID, str], Any] | None = None,
    ) -> dict[str, Any]:
        base = FeedbackService.list_message_feedback(
            db=db,
            tenant_id=tenant_id,
            account_id=account_id,
            conversation_id=conversation_id,
            message_id=message_id,
            min_rating=min_rating,
            max_rating=max_rating,
            skip=skip,
            limit=limit,
            ensure_member_fn=ensure_member_fn,
        )

        rows: list[MessageFeedback] = list(base["items"])
        message_ids = [row.message_id for row in rows if getattr(row, "message_id", None) is not None]
        conversation_ids = [row.conversation_id for row in rows if getattr(row, "conversation_id", None) is not None]

        message_map: dict[UUID, Message] = {}
        if message_ids:
            messages = (
                db.query(Message)
                .filter(Message.tenant_id == tenant_id, Message.id.in_(message_ids))
                .all()
            )
            message_map = {item.id: item for item in messages}

        conversation_map: dict[UUID, Conversation] = {}
        if conversation_ids:
            conversations = (
                db.query(Conversation)
                .filter(Conversation.tenant_id == tenant_id, Conversation.id.in_(conversation_ids))
                .all()
            )
            conversation_map = {item.id: item for item in conversations}

        items: list[MessageFeedback] = []
        for fb in rows:
            msg = message_map.get(fb.message_id)
            conv = conversation_map.get(fb.conversation_id)
            fb.conversation_title = str(getattr(conv, "title", "") or "").strip() or None
            content = str(getattr(msg, "content", "") or "").strip()
            fb.message_content = content[:4000] if content else None
            fb.message_created_at = getattr(msg, "created_at", None)
            items.append(fb)

        return {"total": int(base["total"]), "items": items}

    @staticmethod
    def patch_message_feedback(
        *,
        db: Session,
        tenant_id: UUID,
        account_id: str,
        feedback_id: UUID,
        archived: bool | None,
        ensure_member_fn: Callable[[Session, UUID, str], Any] | None = None,
    ) -> MessageFeedback:
        FeedbackService._ensure_member(
            db=db,
            tenant_id=tenant_id,
            account_id=account_id,
            ensure_member_fn=ensure_member_fn,
        )
        row = (
            db.query(MessageFeedback)
            .filter(MessageFeedback.tenant_id == tenant_id, MessageFeedback.id == feedback_id)
            .first()
        )
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Feedback not found")

        payload = dict(getattr(row, "extra", {}) or {})
        if archived is not None:
            payload["archived"] = bool(archived)
            if archived:
                payload["archived_at"] = datetime.now(UTC).isoformat()
                payload["archived_by"] = str(account_id or "")
            else:
                payload.pop("archived_at", None)
                payload.pop("archived_by", None)

        row.extra = payload
        db.commit()
        db.refresh(row)
        return row

    @staticmethod
    def build_feedback_loop_candidates(
        *,
        db: Session,
        tenant_id: UUID,
        account_id: str,
        max_rating: int = 2,
        limit: int = 200,
        ruleset: IndustryRuleset | None = None,
        ensure_member_fn: Callable[[Session, UUID, str], Any] | None = None,
    ) -> dict[str, Any]:
        FeedbackService._ensure_member(
            db=db,
            tenant_id=tenant_id,
            account_id=account_id,
            ensure_member_fn=ensure_member_fn,
        )
        listed = FeedbackService.list_message_feedback(
            db=db,
            tenant_id=tenant_id,
            account_id=account_id,
            conversation_id=None,
            message_id=None,
            min_rating=1,
            max_rating=max(1, int(max_rating or 2)),
            skip=0,
            limit=max(1, int(limit or 1)),
            ensure_member_fn=None,
        )
        feedback_rows: list[MessageFeedback] = list(listed.get("items") or [])
        if not feedback_rows:
            return build_feedback_loop_candidate_payload([], ruleset=ruleset, max_rating=max_rating)

        message_ids = [row.message_id for row in feedback_rows if getattr(row, "message_id", None) is not None]
        conversation_ids = [row.conversation_id for row in feedback_rows if getattr(row, "conversation_id", None) is not None]

        assistant_map: dict[UUID, Message] = {}
        if message_ids:
            assistants = (
                db.query(Message)
                .filter(Message.tenant_id == tenant_id, Message.id.in_(message_ids))
                .all()
            )
            assistant_map = {item.id: item for item in assistants}

        conversation_map: dict[UUID, Conversation] = {}
        if conversation_ids:
            conversations = (
                db.query(Conversation)
                .filter(Conversation.tenant_id == tenant_id, Conversation.id.in_(conversation_ids))
                .all()
            )
            conversation_map = {item.id: item for item in conversations}

        conversation_messages: list[Message] = []
        if conversation_ids:
            conversation_messages = (
                db.query(Message)
                .filter(Message.tenant_id == tenant_id, Message.conversation_id.in_(conversation_ids))
                .all()
            )

        candidate_rows: list[dict[str, Any]] = []
        for fb in feedback_rows:
            assistant = assistant_map.get(fb.message_id)
            conv = conversation_map.get(fb.conversation_id)
            if assistant is None:
                continue

            extra = dict(getattr(fb, "extra", {}) or {}) if isinstance(getattr(fb, "extra", None), dict) else {}
            meta = (
                dict(getattr(assistant, "message_metadata", {}) or {})
                if isinstance(getattr(assistant, "message_metadata", None), dict)
                else {}
            )
            dataset_id = _safe_text(meta.get("dataset_id") or extra.get("dataset_id") or getattr(conv, "dataset_id", None), max_len=128)
            retrieval_trace = extra.get("retrieval_trace") if isinstance(extra.get("retrieval_trace"), dict) else {}

            candidate_rows.append(
                {
                    "feedback_id": str(fb.id),
                    "rating": int(fb.rating),
                    "reason": getattr(fb, "reason", None),
                    "tags": list(getattr(fb, "tags", []) or []),
                    "expected_answer": getattr(fb, "expected_answer", None),
                    "dataset_id": dataset_id or None,
                    "conversation_id": str(getattr(fb, "conversation_id", "") or ""),
                    "message_id": str(getattr(fb, "message_id", "") or ""),
                    "original_query": _previous_user_question(
                        messages=conversation_messages,
                        conversation_id=fb.conversation_id,
                        assistant_created_at=getattr(assistant, "created_at", None),
                    ),
                    "reference_sources": _feedback_loop_reference_sources(getattr(assistant, "citations", None)),
                    "retrieval_trace": retrieval_trace,
                }
            )

        return build_feedback_loop_candidate_payload(
            candidate_rows,
            ruleset=ruleset,
            max_rating=max_rating,
        )
