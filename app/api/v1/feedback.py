"""
User feedback API (evaluation loop).
Currently provides minimal loop capability:
- Submit rating/reason/expected answer for assistant messages
- List queries (isolated by tenant)
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.evidence import EvidenceItemOut
from app.api.schemas.feedback import (
    MessageFeedbackCreateRequest,
    MessageFeedbackEnrichedList,
    MessageFeedbackList,
    MessageFeedbackOut,
    MessageFeedbackPatchRequest,
)
from app.api.schemas.regression import RagasRegressionCaseOut
from app.core.database import get_db
from app.models.chat import Conversation, Message
from app.models.evaluation import RagasRegressionCase
from app.models.evidence import EvidenceItem, EvidenceSuite
from app.models.feedback import MessageFeedback
from app.rag.core.logging import get_logger
from app.rag.feedback_loop.dispatcher import dispatch_feedback_loop_batch
from app.rag.industry_rules.loaders.yaml_loader import load_ruleset, ruleset_exists
from app.services.audit_log_service import audit_log_event
from app.services.dataset_service import DatasetService
from app.services.feedback_service import FeedbackService
from app.services.rag_trace_service import list_rag_traces

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

router = APIRouter(tags=["Feedback"], responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
logger = get_logger(__name__)


class FeedbackToRegressionCaseRequest(BaseModel):
    include_document_scope: bool = True
    tags: list[str] = []
    extra: dict = {}


class FeedbackToEvidenceItemRequest(BaseModel):
    suite_id: UUID
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
    for item in (getattr(traces, "items", []) or []):
        if str(getattr(item, "request_id", "") or "") != rid:
            continue
        if hasattr(item, "model_dump"):
            return item.model_dump(mode="json")
        if isinstance(item, dict):
            return dict(item)
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


@router.post("/messages", response_model=MessageFeedbackOut, status_code=status.HTTP_201_CREATED, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def upsert_message_feedback(
    request: MessageFeedbackCreateRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Submit feedback for an assistant message (idempotent: resubmit will update)."""
    return FeedbackService.upsert_message_feedback(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        message_id=request.message_id,
        rating=request.rating,
        reason=request.reason,
        tags=request.tags,
        expected_answer=request.expected_answer,
        extra=request.extra if isinstance(request.extra, dict) else {},
        ensure_member_fn=DatasetService.ensure_member,
        list_rag_traces_fn=list_rag_traces,
    )


@router.get("/messages", response_model=MessageFeedbackList, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def list_message_feedback(
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    conversation_id: UUID | None = None,
    message_id: UUID | None = None,
    min_rating: int | None = None,
    max_rating: int | None = None,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Query feedback list (returns all items in current tenant by default)."""
    return FeedbackService.list_message_feedback(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        conversation_id=conversation_id,
        message_id=message_id,
        min_rating=min_rating,
        max_rating=max_rating,
        skip=skip,
        limit=limit,
        ensure_member_fn=DatasetService.ensure_member,
    )


@router.get("/messages/enriched", response_model=MessageFeedbackEnrichedList, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def list_message_feedback_enriched(
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    conversation_id: UUID | None = None,
    message_id: UUID | None = None,
    min_rating: int | None = None,
    max_rating: int | None = None,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Feedback list with joined message content + conversation title (for triage dashboards)."""
    return FeedbackService.list_message_feedback_enriched(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        conversation_id=conversation_id,
        message_id=message_id,
        min_rating=min_rating,
        max_rating=max_rating,
        skip=skip,
        limit=limit,
        ensure_member_fn=DatasetService.ensure_member,
    )


@router.patch("/messages/{feedback_id}", response_model=MessageFeedbackOut, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def patch_message_feedback(
    feedback_id: UUID,
    request: MessageFeedbackPatchRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Patch mutable feedback triage fields."""
    return FeedbackService.patch_message_feedback(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        feedback_id=feedback_id,
        archived=request.archived,
        ensure_member_fn=DatasetService.ensure_member,
    )


@router.get("/loop/candidates", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def preview_feedback_loop_candidates(
    max_rating: Annotated[int, Query(ge=1, le=5)] = 2,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
    ruleset: str | None = None,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Preview feedback-loop candidates from real negative feedback.

    Read-only by design: this endpoint does not write hard negatives, rules, or
    models. Review/promote flows should use the returned candidates explicitly.
    """
    ruleset_obj = None
    ruleset_name = str(ruleset or "").strip()
    if ruleset_name:
        if not ruleset_exists(ruleset_name):
            raise HTTPException(status_code=404, detail="Industry ruleset not found")
        ruleset_obj = load_ruleset(ruleset_name)
    return FeedbackService.build_feedback_loop_candidates(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        max_rating=int(max_rating),
        limit=int(limit),
        ruleset=ruleset_obj,
        ensure_member_fn=DatasetService.ensure_member,
    )


@router.post("/loop/hard-negatives/export", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def export_feedback_loop_hard_negatives(
    max_rating: Annotated[int, Query(ge=1, le=5)] = 2,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
    dry_run: Annotated[bool, Query()] = True,
    append: Annotated[bool, Query()] = True,
    ruleset: str | None = None,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Batch-export feedback-derived hard negatives.

    Safe defaults:
    - `dry_run=true` previews counts without writing JSONL.
    - No realtime insert listener is registered.
    - Exported JSONL is PII-safe and contains lineage ids for audit/review.
    """
    ruleset_obj = None
    ruleset_name = str(ruleset or "").strip()
    if ruleset_name:
        if not ruleset_exists(ruleset_name):
            raise HTTPException(status_code=404, detail="Industry ruleset not found")
        ruleset_obj = load_ruleset(ruleset_name)
    return dispatch_feedback_loop_batch(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        max_rating=int(max_rating),
        limit=int(limit),
        dry_run=bool(dry_run),
        append=bool(append),
        trigger="manual",
        ruleset=ruleset_obj,
        ensure_member_fn=DatasetService.ensure_member,
    )


@router.post("/messages/{feedback_id}/to-regression-case", response_model=RagasRegressionCaseOut, status_code=201, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def create_regression_case_from_feedback(
    feedback_id: UUID,
    body: FeedbackToRegressionCaseRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
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
    except Exception as exc:
        logger.debug("Ignoring non-critical feedback fallback failure: %s", exc)

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


@router.post("/messages/{feedback_id}/to-evidence-item", response_model=EvidenceItemOut, status_code=201, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def create_evidence_item_from_feedback(
    feedback_id: UUID,
    body: FeedbackToEvidenceItemRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Convert a feedback entry into an EvidenceSuite item.

    Intended workflow:
    feedback -> draft EvidenceItem -> review/approve -> sync into regression cases.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)

    suite_id = getattr(body, "suite_id", None)
    suite = (
        db.query(EvidenceSuite)
        .filter(EvidenceSuite.id == suite_id, EvidenceSuite.tenant_id == tenant_id)
        .first()
    )
    if not suite:
        raise HTTPException(status_code=404, detail="Evidence suite not found")
    if getattr(suite, "archived_at", None) is not None:
        raise HTTPException(status_code=400, detail="Evidence suite is archived")

    # Ensure user can at least read the suite's dataset.
    ds = DatasetService.get_dataset(db, tenant_id, suite.dataset_id)
    DatasetService.assert_dataset_readable(db, ds, account_id)

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
        question = "(missing user question)"

    # Resolve dataset_id (best-effort).
    meta = assistant.message_metadata if isinstance(getattr(assistant, "message_metadata", None), dict) else {}
    dataset_id: UUID | None = None
    raw_ds = meta.get("dataset_id") if isinstance(meta, dict) else None
    if isinstance(raw_ds, str) and raw_ds.strip():
        try:
            dataset_id = UUID(raw_ds.strip())
        except Exception:
            dataset_id = None
    if dataset_id is None:
        dataset_id = getattr(conv, "dataset_id", None)
    if dataset_id is not None and dataset_id != suite.dataset_id:
        raise HTTPException(status_code=400, detail="Feedback dataset_id does not match evidence suite dataset_id")

    request_id = str(meta.get("request_id") or "").strip() if isinstance(meta, dict) else ""

    tags: list[str] = []
    if isinstance(fb.tags, list):
        tags.extend([str(x) for x in fb.tags if isinstance(x, (str, int, float))])
    if isinstance(getattr(body, "tags", None), list):
        tags.extend([str(x) for x in body.tags if isinstance(x, (str, int, float))])
    # Normalize: unique + cap.
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

    # Best-effort: normalize/validate pointers (do not block draft creation on failures).
    try:
        if dataset_id is not None and reference_sources:
            from app.api.v1.evaluations import _finalize_reference_sources  # noqa: WPS433

            reference_sources = _finalize_reference_sources(
                db,
                tenant_id=tenant_id,
                account_id=account_id,
                dataset_id=dataset_id,
                reference_sources=reference_sources,
            )
    except Exception as exc:
        logger.debug("Ignoring non-critical feedback fallback failure: %s", exc)

    retrieval_snapshot: dict[str, Any] = trace_payload if isinstance(trace_payload, dict) else {}
    rag_config_snapshot: dict[str, Any] = {}
    if isinstance(trace_payload, dict):
        retrieval = trace_payload.get("retrieval")
        if isinstance(retrieval, dict):
            rag_config_snapshot.update(retrieval)

    source_metadata: dict[str, Any] = {
        **extra,
        "conversation_id": str(conv.id),
        "request_id": request_id or None,
    }

    row = EvidenceItem(
        tenant_id=tenant_id,
        dataset_id=(dataset_id or suite.dataset_id),
        suite_id=suite.id,
        status="draft",
        query=question,
        expected_answer=fb.expected_answer,
        tags=cleaned,
        source_metadata=source_metadata,
        reference_sources=reference_sources,
        retrieval_snapshot=retrieval_snapshot,
        rag_config_snapshot=rag_config_snapshot,
        notes=(str(fb.reason or "").strip()[:2000] if fb.reason else None),
        created_by=account_id,
    )
    db.add(row)
    try:
        db.flush()
    except Exception as exc:
        logger.debug("Ignoring non-critical feedback fallback failure: %s", exc)

    audit_log_event(
        db,
        tenant_id=tenant_id,
        actor_id=account_id,
        action="evidence.item.create_from_feedback",
        resource_type="evidence_item",
        resource_id=str(getattr(row, "id", "") or ""),
        details={
            "feedback_id": str(fb.id),
            "message_id": str(fb.message_id),
            "suite_id": str(suite.id),
            "dataset_id": str(suite.dataset_id),
            "rating": int(fb.rating),
            "reference_sources": len(reference_sources or []),
        },
    )
    db.commit()
    db.refresh(row)
    return row
