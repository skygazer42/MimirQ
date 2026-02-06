"""
User feedback API (evaluation loop).
Currently provides minimal loop capability:
- Submit rating/reason/expected answer for assistant messages
- List queries (isolated by tenant)
"""


from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.feedback import (
    MessageFeedbackCreateRequest,
    MessageFeedbackEnrichedList,
    MessageFeedbackList,
    MessageFeedbackOut,
)
from app.api.schemas.regression import RagasRegressionCaseOut
from app.core.database import get_db
from app.models.chat import Conversation, Message
from app.models.evaluation import RagasRegressionCase
from app.models.feedback import MessageFeedback
from app.services.audit_log_service import audit_log_event
from app.services.dataset_service import DatasetService
from app.services.rag_trace_service import list_rag_traces

router = APIRouter(tags=["Feedback"])


class FeedbackToRegressionCaseRequest(BaseModel):
    include_document_scope: bool = True
    tags: list[str] = []
    extra: dict = {}


def _coerce_uuid(value: Any) -> UUID | None:
    if value is None:
        return None
    try:
        text = str(value).strip()
        if not text:
            return None
        return UUID(text)
    except Exception:
        return None


def _coerce_int(value: Any, *, min_value: int | None = None) -> int | None:
    try:
        if value is None:
            return None
        out = int(value)
    except Exception:
        return None
    if min_value is not None and out < min_value:
        return None
    return out


def _extract_reference_sources(citations: Any) -> list[dict]:
    if not isinstance(citations, list):
        return []
    out: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for item in citations:
        if not isinstance(item, dict):
            continue
        doc_id = _coerce_uuid(item.get("document_id"))
        chunk_id = _coerce_uuid(item.get("chunk_id"))
        if doc_id is None or chunk_id is None:
            continue
        key = (str(doc_id), str(chunk_id))
        if key in seen:
            continue
        seen.add(key)

        payload: dict[str, Any] = {
            "document_id": str(doc_id),
            "chunk_id": str(chunk_id),
        }
        page_number = _coerce_int(item.get("page_number"), min_value=1)
        if page_number is not None:
            payload["page_number"] = page_number
        start_char = _coerce_int(item.get("start_char"), min_value=0)
        if start_char is not None:
            payload["start_char"] = start_char
        end_char = _coerce_int(item.get("end_char"), min_value=0)
        if end_char is not None:
            payload["end_char"] = end_char
        chunk_index = _coerce_int(item.get("chunk_index"), min_value=0)
        if chunk_index is not None:
            payload["chunk_index"] = chunk_index
        for key_name in ("doc_pipeline_key", "pipeline_hash", "quote", "label"):
            raw = item.get(key_name)
            if raw is None:
                continue
            text = str(raw).strip()
            if text:
                payload[key_name] = text[:2000] if key_name == "quote" else text[:128]
        out.append(payload)
        if len(out) >= 100:
            break
    return out


def _find_trace_by_request_id(*, tenant_id: UUID, conversation_id: UUID, request_id: str) -> dict | None:
    rid = str(request_id or "").strip()
    if not rid:
        return None
    try:
        traces = list_rag_traces(
            tenant_id=str(tenant_id),
            conversation_id=str(conversation_id),
            limit=100,
            window_minutes=7 * 24 * 60,
            max_bytes=10_000_000,
        )
    except Exception:
        return None
    for item in list(getattr(traces, "items", []) or []):
        if str(getattr(item, "request_id", "") or "") != rid:
            continue
        if hasattr(item, "model_dump"):
            return item.model_dump(mode="json")
        if isinstance(item, dict):
            return dict(item)
        return None
    return None


@router.post("/messages", response_model=MessageFeedbackOut, status_code=status.HTTP_201_CREATED)
async def upsert_message_feedback(
    request: MessageFeedbackCreateRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """Submit feedback for an assistant message (idempotent: resubmit will update)."""
    DatasetService.ensure_member(db, tenant_id, account_id)

    msg = (
        db.query(Message)
        .filter(Message.id == request.message_id, Message.tenant_id == tenant_id)
        .first()
    )
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")
    if (msg.role or "").lower() != "assistant":
        raise HTTPException(status_code=400, detail="Only assistant messages can be rated")

    row = (
        db.query(MessageFeedback)
        .filter(
            MessageFeedback.tenant_id == tenant_id,
            MessageFeedback.message_id == msg.id,
            MessageFeedback.account_id == account_id,
        )
        .first()
    )
    if row:
        row.rating = request.rating
        row.reason = request.reason
        row.tags = request.tags
        row.expected_answer = request.expected_answer
        row.extra = request.extra
        db.commit()
        db.refresh(row)
        return row

    row = MessageFeedback(
        tenant_id=tenant_id,
        conversation_id=msg.conversation_id,
        message_id=msg.id,
        account_id=account_id,
        rating=request.rating,
        reason=request.reason,
        tags=request.tags,
        expected_answer=request.expected_answer,
        extra=request.extra,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/messages", response_model=MessageFeedbackList)
async def list_message_feedback(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    conversation_id: UUID | None = None,
    message_id: UUID | None = None,
    min_rating: int | None = None,
    max_rating: int | None = None,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """Query feedback list (returns all items in current tenant by default)."""
    DatasetService.ensure_member(db, tenant_id, account_id)

    query = db.query(MessageFeedback).filter(MessageFeedback.tenant_id == tenant_id)
    if conversation_id:
        query = query.filter(MessageFeedback.conversation_id == conversation_id)
    if message_id:
        query = query.filter(MessageFeedback.message_id == message_id)
    if min_rating is not None:
        query = query.filter(MessageFeedback.rating >= int(min_rating))
    if max_rating is not None:
        query = query.filter(MessageFeedback.rating <= int(max_rating))

    total = query.count()
    rows = (
        query.order_by(MessageFeedback.updated_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return {"total": total, "items": rows}


@router.get("/messages/enriched", response_model=MessageFeedbackEnrichedList)
async def list_message_feedback_enriched(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    conversation_id: UUID | None = None,
    message_id: UUID | None = None,
    min_rating: int | None = None,
    max_rating: int | None = None,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """Feedback list with joined message content + conversation title (for triage dashboards)."""
    DatasetService.ensure_member(db, tenant_id, account_id)

    query = (
        db.query(
            MessageFeedback,
            Message.content,
            Message.created_at,
            Conversation.title,
        )
        .join(Message, Message.id == MessageFeedback.message_id)
        .join(Conversation, Conversation.id == MessageFeedback.conversation_id)
        .filter(
            MessageFeedback.tenant_id == tenant_id,
            Message.tenant_id == tenant_id,
            Conversation.tenant_id == tenant_id,
        )
    )

    if conversation_id:
        query = query.filter(MessageFeedback.conversation_id == conversation_id)
    if message_id:
        query = query.filter(MessageFeedback.message_id == message_id)
    if min_rating is not None:
        query = query.filter(MessageFeedback.rating >= int(min_rating))
    if max_rating is not None:
        query = query.filter(MessageFeedback.rating <= int(max_rating))

    total = query.count()
    rows = (
        query.order_by(MessageFeedback.updated_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    items = []
    for fb, msg_content, msg_created_at, conv_title in rows:
        # Attach non-persisted attrs for Pydantic serialization.
        fb.conversation_title = conv_title
        content = (msg_content or "").strip()
        fb.message_content = content[:4000] if content else None
        fb.message_created_at = msg_created_at
        items.append(fb)

    return {"total": total, "items": items}


@router.post("/messages/{feedback_id}/to-regression-case", response_model=RagasRegressionCaseOut, status_code=201)
async def create_regression_case_from_feedback(
    feedback_id: UUID,
    body: FeedbackToRegressionCaseRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """
    Convert a feedback entry into a RAGAS regression case.

    Heuristics:
    - Question is inferred from the latest user message before the rated assistant message.
    - dataset_id is read from assistant message metadata when available.
    - document_ids scope is inherited from the conversation when requested.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)

    fb = (
        db.query(MessageFeedback)
        .filter(MessageFeedback.id == feedback_id, MessageFeedback.tenant_id == tenant_id)
        .first()
    )
    if not fb:
        raise HTTPException(status_code=404, detail="Feedback not found")

    assistant = (
        db.query(Message)
        .filter(Message.id == fb.message_id, Message.tenant_id == tenant_id)
        .first()
    )
    if not assistant:
        raise HTTPException(status_code=404, detail="Assistant message not found")

    conv = (
        db.query(Conversation)
        .filter(Conversation.id == fb.conversation_id, Conversation.tenant_id == tenant_id)
        .first()
    )
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    # Infer question from last user message before the assistant answer.
    q_msg = (
        db.query(Message)
        .filter(
            Message.tenant_id == tenant_id,
            Message.conversation_id == conv.id,
            Message.role == "user",
            Message.created_at <= assistant.created_at,
        )
        .order_by(Message.created_at.desc())
        .first()
    )
    question = (q_msg.content if q_msg else "").strip()
    if not question:
        # Fallback: keep a stable placeholder to avoid empty regression cases.
        question = "(missing user question)"

    dataset_id: UUID | None = None
    meta = assistant.message_metadata if isinstance(getattr(assistant, "message_metadata", None), dict) else {}
    raw_ds = meta.get("dataset_id") if isinstance(meta, dict) else None
    if isinstance(raw_ds, str) and raw_ds.strip():
        try:
            dataset_id = UUID(raw_ds.strip())
        except Exception:
            dataset_id = None
    request_id = str(meta.get("request_id") or "").strip() if isinstance(meta, dict) else ""

    doc_ids: list[str] = []
    if bool(getattr(body, "include_document_scope", True)):
        doc_ids = [str(x) for x in (conv.document_ids or [])]

    tags: list[str] = []
    if isinstance(fb.tags, list):
        tags.extend([str(x) for x in fb.tags if isinstance(x, (str, int, float))])
    if isinstance(getattr(body, "tags", None), list):
        tags.extend([str(x) for x in body.tags if isinstance(x, (str, int, float))])
    # Small normalization: unique + cap.
    seen: set[str] = set()
    cleaned: list[str] = []
    for t in tags:
        v = str(t or "").strip()
        if not v:
            continue
        key = v.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(v[:64])
        if len(cleaned) >= 30:
            break

    extra: dict = {}
    if isinstance(fb.extra, dict):
        extra.update(fb.extra)
    if isinstance(getattr(body, "extra", None), dict):
        extra.update(body.extra)
    extra.setdefault("source", "feedback")
    extra.setdefault("feedback_id", str(fb.id))
    extra.setdefault("message_id", str(fb.message_id))
    extra.setdefault("rating", int(fb.rating))

    reference_sources = _extract_reference_sources(getattr(assistant, "citations", None))
    trace_payload = _find_trace_by_request_id(tenant_id=tenant_id, conversation_id=conv.id, request_id=request_id)
    if trace_payload and isinstance(trace_payload, dict):
        extra["retrieval_trace"] = trace_payload
        extra["retrieval_trace_request_id"] = request_id
        if not reference_sources:
            reference_sources = _extract_reference_sources(trace_payload.get("citations"))

    row = RagasRegressionCase(
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        document_ids=doc_ids,
        question=question,
        expected_answer=fb.expected_answer,
        reference_sources=reference_sources,
        tags=cleaned,
        extra=extra,
        created_by=account_id,
    )
    db.add(row)
    try:
        db.flush()
    except Exception:
        pass

    # Best-effort audit log (commit in the same transaction).
    audit_log_event(
        db,
        tenant_id=tenant_id,
        actor_id=account_id,
        action="regression.case.create_from_feedback",
        resource_type="regression_case",
        resource_id=str(getattr(row, "id", "") or ""),
        details={
            "feedback_id": str(fb.id),
            "message_id": str(fb.message_id),
            "rating": int(fb.rating),
            "dataset_id": str(dataset_id) if dataset_id else None,
            "document_count": len(doc_ids),
        },
    )
    db.commit()
    db.refresh(row)
    return row
