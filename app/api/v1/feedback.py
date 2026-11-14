"""
User feedback API (evaluation loop).
Currently provides minimal loop capability:
- Submit rating/reason/expected answer for assistant messages
- List queries (isolated by tenant)
"""

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_account_id, get_tenant_id
from app.api.schemas.conversations import (
    FeedbackLoopCandidatesQuery,
    FeedbackLoopCandidatesResponse,
    FeedbackLoopExportQuery,
    FeedbackLoopExportResponse,
    FeedbackToEvidenceItemRequest,
    FeedbackToRegressionCaseRequest,
    MessageFeedbackCreateRequest,
    MessageFeedbackEnrichedList,
    MessageFeedbackList,
    MessageFeedbackListQuery,
    MessageFeedbackOut,
    MessageFeedbackPatchRequest,
)
from app.api.schemas.evaluation import EvidenceItemOut, RagasRegressionCaseOut
from app.api.utils import DEFAULT_HTTP_EXCEPTION_RESPONSES as _DEFAULT_HTTP_EXCEPTION_RESPONSES
from app.core.database import get_db
from app.models.chat import Conversation, Message
from app.models.evaluation import RagasRegressionCase
from app.models.evidence import EvidenceItem, EvidenceSuite
from app.models.feedback import MessageFeedback
from app.rag.core.logging import get_logger
from app.rag.feedback_loop.dispatcher import dispatch_feedback_loop_batch
from app.rag.industry_rules.loaders.yaml_loader import load_ruleset, ruleset_exists
from app.services import dataset_service, feedback_service
from app.services.audit_log_service import audit_log_event
from app.services.rag_trace_service import list_rag_traces
from app.services.rbac_service import TenantPermissions, ensure_tenant_permission

router = APIRouter(tags=["Feedback"], responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
logger = get_logger(__name__)
_FEEDBACK_FALLBACK_LOG_MESSAGE = "Ignoring non-critical feedback fallback failure: %s"
_REGRESSION_CASE_PROTECTED_EXTRA_KEYS = frozenset(
    {
        "source",
        "feedback_id",
        "message_id",
        "rating",
        "feedback_category",
        "feedback_category_source",
        "dataset_id",
        "query_hash",
        "retrieval_trace_ref",
        "profile",
        "judge_score_ref",
        "retrieval_trace",
        "retrieval_trace_request_id",
    }
)


def _coerce_uuid(value: Any) -> UUID | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return UUID(text)
    except ValueError:
        return None


def _coerce_int(value: Any, *, min_value: int | None = None) -> int | None:
    if value is None:
        return None
    try:
        out = int(value)
    except (ValueError, TypeError, OverflowError):
        return None
    if min_value is not None and out < min_value:
        return None
    return out


def _build_reference_source_payload(item: dict[str, Any], *, doc_id: UUID, chunk_id: UUID) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "document_id": str(doc_id),
        "chunk_id": str(chunk_id),
    }
    optional_ints = (
        ("page_number", 1),
        ("start_char", 0),
        ("end_char", 0),
        ("chunk_index", 0),
    )
    for key_name, min_value in optional_ints:
        value = _coerce_int(item.get(key_name), min_value=min_value)
        if value is not None:
            payload[key_name] = value
    for key_name, max_length in (
        ("doc_pipeline_key", 128),
        ("pipeline_hash", 128),
        ("quote", 2000),
        ("label", 128),
    ):
        raw = item.get(key_name)
        if raw is None:
            continue
        text = str(raw).strip()
        if text:
            payload[key_name] = text[:max_length]
    return payload


def _extract_reference_sources(citations: Any) -> list[dict[str, Any]]:
    if not isinstance(citations, list):
        return []
    out: list[dict[str, Any]] = []
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
        out.append(_build_reference_source_payload(item, doc_id=doc_id, chunk_id=chunk_id))
        if len(out) >= 100:
            break
    return out


def _find_trace_by_request_id(
    *, tenant_id: UUID, conversation_id: UUID, request_id: str | None
) -> dict[str, Any] | None:
    if request_id is None:
        return None
    normalized_request_id = request_id.strip()
    if not normalized_request_id:
        return None
    try:
        traces = list_rag_traces(
            tenant_id=str(tenant_id),
            conversation_id=str(conversation_id),
            limit=100,
            window_minutes=7 * 24 * 60,
            max_bytes=10_000_000,
        )
    except Exception as exc:
        logger.debug(_FEEDBACK_FALLBACK_LOG_MESSAGE, exc, exc_info=True)
        return None
    for item in traces.items:
        if item.request_id != normalized_request_id:
            continue
        return item.model_dump(mode="json")
    return None


def _normalize_feedback_tags(*tag_groups: Any) -> list[str]:
    tags: list[str] = []
    for group in tag_groups:
        if not isinstance(group, list):
            continue
        tags.extend(str(value) for value in group if isinstance(value, (str, int, float)))

    seen: set[str] = set()
    cleaned: list[str] = []
    for tag in tags:
        value = tag.strip()
        if not value:
            continue
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(value[:64])
        if len(cleaned) >= 30:
            break
    return cleaned


def _get_feedback_for_promotion(db: Session, *, tenant_id: UUID, feedback_id: UUID) -> MessageFeedback:
    feedback = (
        db.query(MessageFeedback)
        .filter(MessageFeedback.id == feedback_id, MessageFeedback.tenant_id == tenant_id)
        .with_for_update()
        .first()
    )
    if feedback is None:
        raise HTTPException(status_code=404, detail="Feedback not found")
    return feedback


def _get_feedback_assistant_message(db: Session, *, tenant_id: UUID, message_id: UUID) -> Message:
    assistant = db.query(Message).filter(Message.id == message_id, Message.tenant_id == tenant_id).first()
    if assistant is None:
        raise HTTPException(status_code=404, detail="Assistant message not found")
    return assistant


def _get_feedback_conversation(db: Session, *, tenant_id: UUID, conversation_id: UUID) -> Conversation:
    conversation = (
        db.query(Conversation).filter(Conversation.id == conversation_id, Conversation.tenant_id == tenant_id).first()
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return conversation


def _infer_feedback_question(
    db: Session,
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    assistant_created_at: datetime,
) -> str:
    user_message = (
        db.query(Message)
        .filter(
            Message.tenant_id == tenant_id,
            Message.conversation_id == conversation_id,
            Message.role == "user",
            Message.created_at <= assistant_created_at,
        )
        .order_by(Message.created_at.desc())
        .first()
    )
    if user_message is None:
        return "(missing user question)"
    question = user_message.content.strip()
    return question or "(missing user question)"


def _resolve_feedback_dataset_id(
    assistant: Message,
    conversation: Conversation,
) -> tuple[UUID | None, str | None]:
    meta = assistant.message_metadata if isinstance(assistant.message_metadata, dict) else {}
    dataset_id: UUID | None = None
    metadata_dataset_id = meta.get("dataset_id")
    if isinstance(metadata_dataset_id, str) and metadata_dataset_id.strip():
        try:
            dataset_id = UUID(metadata_dataset_id.strip())
        except ValueError:
            dataset_id = None
    if dataset_id is None:
        dataset_id = conversation.dataset_id
    request_id = meta.get("request_id")
    if request_id is not None:
        request_id = request_id.strip()
    return dataset_id, request_id


def _hydrate_feedback_trace_payload(
    *,
    tenant_id: UUID,
    conversation_id: UUID,
    request_id: str | None,
    citations: Any,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    reference_sources = _extract_reference_sources(citations)
    trace_payload = _find_trace_by_request_id(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        request_id=request_id,
    )
    if trace_payload is not None and not reference_sources:
        reference_sources = _extract_reference_sources(trace_payload["citations"])
    return reference_sources, trace_payload


def _build_regression_case_extra(
    *,
    feedback: MessageFeedback,
    body_extra: dict[str, Any],
    dataset_id: UUID | None,
) -> dict[str, Any]:
    extra: dict[str, Any] = {}
    if isinstance(feedback.extra, dict):
        extra.update(feedback.extra)
    extra.update({key: value for key, value in body_extra.items() if key not in _REGRESSION_CASE_PROTECTED_EXTRA_KEYS})
    extra["source"] = "feedback"
    extra["feedback_id"] = str(feedback.id)
    extra["message_id"] = str(feedback.message_id)
    extra["rating"] = feedback.rating
    if dataset_id is not None:
        extra["dataset_id"] = str(dataset_id)
    if feedback.category:
        extra["feedback_category"] = feedback.category
        extra["feedback_category_source"] = feedback.category_source
    return extra


def _finalize_feedback_reference_sources_or_keep_original(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    dataset_id: UUID,
    reference_sources: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not reference_sources:
        return reference_sources
    try:
        from app.services.evaluation_reference_sources import finalize_reference_sources

        return finalize_reference_sources(
            db,
            tenant_id=tenant_id,
            account_id=account_id,
            dataset_id=dataset_id,
            reference_sources=reference_sources,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.debug(_FEEDBACK_FALLBACK_LOG_MESSAGE, exc, exc_info=True)
    return reference_sources


@router.post(
    "/messages",
    response_model=MessageFeedbackOut,
    status_code=status.HTTP_201_CREATED,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def upsert_message_feedback(
    request: MessageFeedbackCreateRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> MessageFeedback:
    """Submit feedback for an assistant message (idempotent: resubmit will update)."""
    return feedback_service.upsert_message_feedback(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        message_id=request.message_id,
        rating=request.rating,
        reason=request.reason,
        tags=request.tags,
        expected_answer=request.expected_answer,
        category=request.category,
        extra=request.extra,
        ensure_member_fn=dataset_service.ensure_member,
    )


@router.get("/messages", response_model=MessageFeedbackList, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def list_message_feedback(
    query: Annotated[MessageFeedbackListQuery, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """Query feedback list (returns all items in current tenant by default)."""
    return feedback_service.list_message_feedback(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        **query.model_dump(),
        ensure_member_fn=dataset_service.ensure_member,
    )


@router.get(
    "/messages/enriched", response_model=MessageFeedbackEnrichedList, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES
)
def list_message_feedback_enriched(
    query: Annotated[MessageFeedbackListQuery, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """Feedback list with joined message content + conversation title (for triage dashboards)."""
    return feedback_service.list_message_feedback_enriched(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        **query.model_dump(),
        ensure_member_fn=dataset_service.ensure_member,
    )


@router.patch("/messages/{feedback_id}", response_model=MessageFeedbackOut, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def patch_message_feedback(
    feedback_id: UUID,
    request: MessageFeedbackPatchRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> MessageFeedback:
    """Patch mutable feedback triage fields."""
    ensure_tenant_permission(
        db,
        tenant_id,
        account_id,
        TenantPermissions.FEEDBACK_TRIAGE_WRITE,
        detail="No permission to triage feedback",
    )
    return feedback_service.patch_message_feedback(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        feedback_id=feedback_id,
        archived=request.archived,
        category=request.category,
        ensure_member_fn=dataset_service.ensure_member,
    )


@router.get(
    "/loop/candidates", response_model=FeedbackLoopCandidatesResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES
)
def preview_feedback_loop_candidates(
    query: Annotated[FeedbackLoopCandidatesQuery, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """
    Preview feedback-loop candidates from real negative feedback.

    Read-only by design: this endpoint does not write hard negatives, rules, or
    models. Review/promote flows should use the returned candidates explicitly.
    """
    ensure_tenant_permission(
        db,
        tenant_id,
        account_id,
        TenantPermissions.FEEDBACK_TRIAGE_WRITE,
        detail="No permission to review feedback candidates",
    )
    ruleset_obj = None
    ruleset_name = query.ruleset.strip() if query.ruleset is not None else None
    if ruleset_name:
        if not ruleset_exists(ruleset_name):
            raise HTTPException(status_code=404, detail="Industry ruleset not found")
        ruleset_obj = load_ruleset(ruleset_name)
    return feedback_service.build_feedback_loop_candidates(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        max_rating=query.max_rating,
        limit=query.limit,
        ruleset=ruleset_obj,
        ensure_member_fn=dataset_service.ensure_member,
    )


@router.post(
    "/loop/hard-negatives/export",
    response_model=FeedbackLoopExportResponse,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def export_feedback_loop_hard_negatives(
    query: Annotated[FeedbackLoopExportQuery, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    """
    Batch-export feedback-derived hard negatives.

    Safe defaults:
    - `dry_run=true` previews counts without writing JSONL.
    - No realtime insert listener is registered.
    - Exported JSONL is PII-safe and contains lineage ids for audit/review.
    """
    ensure_tenant_permission(
        db,
        tenant_id,
        account_id,
        TenantPermissions.FEEDBACK_TRIAGE_WRITE,
        detail="No permission to export feedback candidates",
    )
    ruleset_obj = None
    ruleset_name = query.ruleset.strip() if query.ruleset is not None else None
    if ruleset_name:
        if not ruleset_exists(ruleset_name):
            raise HTTPException(status_code=404, detail="Industry ruleset not found")
        ruleset_obj = load_ruleset(ruleset_name)
    return dispatch_feedback_loop_batch(
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        max_rating=query.max_rating,
        limit=query.limit,
        dry_run=query.dry_run,
        append=query.append,
        trigger="manual",
        ruleset=ruleset_obj,
        ensure_member_fn=dataset_service.ensure_member,
    )


@router.post(
    "/messages/{feedback_id}/to-regression-case",
    response_model=RagasRegressionCaseOut,
    status_code=201,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def create_regression_case_from_feedback(
    feedback_id: UUID,
    body: FeedbackToRegressionCaseRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> RagasRegressionCase:
    """
    Convert a feedback entry into a RAGAS regression case.

    Heuristics:
    - Question is inferred from the latest user message before the rated assistant message.
    - dataset_id is read from assistant message metadata when available.
    - document_ids scope is inherited from the conversation when requested.
    """
    ensure_tenant_permission(
        db,
        tenant_id,
        account_id,
        TenantPermissions.FEEDBACK_TRIAGE_WRITE,
        detail="No permission to promote feedback",
    )

    feedback = _get_feedback_for_promotion(db, tenant_id=tenant_id, feedback_id=feedback_id)
    feedback_extra = dict(feedback.extra) if isinstance(feedback.extra, dict) else {}
    eval_case_status = feedback_extra.get("eval_case_status")
    if eval_case_status is not None and eval_case_status.strip().lower() == "promoted":
        raise HTTPException(status_code=409, detail="Feedback already promoted to a regression case")

    assistant = _get_feedback_assistant_message(db, tenant_id=tenant_id, message_id=feedback.message_id)
    conversation = _get_feedback_conversation(db, tenant_id=tenant_id, conversation_id=feedback.conversation_id)
    question = _infer_feedback_question(
        db,
        tenant_id=tenant_id,
        conversation_id=conversation.id,
        assistant_created_at=assistant.created_at,
    )
    dataset_id, request_id = _resolve_feedback_dataset_id(assistant, conversation)
    if dataset_id is not None:
        dataset = dataset_service.get_dataset(db, tenant_id, dataset_id)
        dataset_service.assert_dataset_writable(db, dataset, account_id)

    document_ids: list[str] = []
    if body.include_document_scope:
        document_ids = [str(document_id) for document_id in (conversation.document_ids or [])]

    category_tags = [feedback.category] if feedback.category else []
    tags = _normalize_feedback_tags(feedback.tags, category_tags, body.tags)
    extra = _build_regression_case_extra(
        feedback=feedback,
        body_extra=body.extra,
        dataset_id=dataset_id,
    )
    reference_sources, trace_payload = _hydrate_feedback_trace_payload(
        tenant_id=tenant_id,
        conversation_id=conversation.id,
        request_id=request_id,
        citations=assistant.citations,
    )
    if trace_payload is not None:
        extra["retrieval_trace"] = trace_payload
        extra["retrieval_trace_request_id"] = request_id

    regression_case = RagasRegressionCase(
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        document_ids=document_ids,
        question=question,
        expected_answer=feedback.expected_answer,
        reference_sources=reference_sources,
        tags=tags,
        extra=extra,
        created_by=account_id,
    )
    db.add(regression_case)
    db.flush()

    feedback_extra["eval_case_status"] = "promoted"
    feedback_extra["eval_case_id"] = str(regression_case.id)
    feedback_extra["eval_case_promoted_by"] = account_id
    feedback.extra = feedback_extra

    # Best-effort audit log (commit in the same transaction).
    audit_log_event(
        db,
        tenant_id=tenant_id,
        actor_id=account_id,
        action="regression.case.create_from_feedback",
        resource_type="regression_case",
        resource_id=str(regression_case.id),
        details={
            "feedback_id": str(feedback.id),
            "message_id": str(feedback.message_id),
            "rating": feedback.rating,
            "dataset_id": str(dataset_id) if dataset_id is not None else None,
            "document_count": len(document_ids),
        },
    )
    db.commit()
    db.refresh(regression_case)
    return regression_case


@router.post(
    "/messages/{feedback_id}/to-evidence-item",
    response_model=EvidenceItemOut,
    status_code=201,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def create_evidence_item_from_feedback(
    feedback_id: UUID,
    body: FeedbackToEvidenceItemRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> EvidenceItem:
    """
    Convert a feedback entry into an EvidenceSuite item.

    Intended workflow:
    feedback -> draft EvidenceItem -> review/approve -> sync into regression cases.
    """
    dataset_service.ensure_member(db, tenant_id, account_id)

    suite_id = body.suite_id
    suite = db.query(EvidenceSuite).filter(EvidenceSuite.id == suite_id, EvidenceSuite.tenant_id == tenant_id).first()
    if suite is None:
        raise HTTPException(status_code=404, detail="Evidence suite not found")
    if suite.archived_at is not None:
        raise HTTPException(status_code=400, detail="Evidence suite is archived")

    # Ensure user can at least read the suite's dataset.
    dataset = dataset_service.get_dataset(db, tenant_id, suite.dataset_id)
    dataset_service.assert_dataset_readable(db, dataset, account_id)

    feedback = _get_feedback_for_promotion(db, tenant_id=tenant_id, feedback_id=feedback_id)
    assistant = _get_feedback_assistant_message(db, tenant_id=tenant_id, message_id=feedback.message_id)
    conversation = _get_feedback_conversation(db, tenant_id=tenant_id, conversation_id=feedback.conversation_id)
    question = _infer_feedback_question(
        db,
        tenant_id=tenant_id,
        conversation_id=conversation.id,
        assistant_created_at=assistant.created_at,
    )
    dataset_id, request_id = _resolve_feedback_dataset_id(assistant, conversation)
    if dataset_id is not None and dataset_id != suite.dataset_id:
        raise HTTPException(status_code=400, detail="Feedback dataset_id does not match evidence suite dataset_id")
    tags = _normalize_feedback_tags(feedback.tags, body.tags)
    extra = dict(feedback.extra) if isinstance(feedback.extra, dict) else {}
    extra.update(body.extra)
    extra.setdefault("source", "feedback")
    extra.setdefault("feedback_id", str(feedback.id))
    extra.setdefault("message_id", str(feedback.message_id))
    extra.setdefault("rating", feedback.rating)
    reference_sources, trace_payload = _hydrate_feedback_trace_payload(
        tenant_id=tenant_id,
        conversation_id=conversation.id,
        request_id=request_id,
        citations=assistant.citations,
    )
    if trace_payload is not None:
        extra["retrieval_trace"] = trace_payload
        extra["retrieval_trace_request_id"] = request_id
    reference_sources = _finalize_feedback_reference_sources_or_keep_original(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=suite.dataset_id,
        reference_sources=reference_sources,
    )

    retrieval_snapshot = trace_payload if trace_payload is not None else {}
    rag_config_snapshot = dict(trace_payload["retrieval"]) if trace_payload is not None else {}

    source_metadata: dict[str, Any] = {
        **extra,
        "conversation_id": str(conversation.id),
        "request_id": request_id,
    }

    evidence_item = EvidenceItem(
        tenant_id=tenant_id,
        dataset_id=suite.dataset_id,
        suite_id=suite.id,
        status="draft",
        query=question,
        expected_answer=feedback.expected_answer,
        tags=tags,
        source_metadata=source_metadata,
        reference_sources=reference_sources,
        retrieval_snapshot=retrieval_snapshot,
        rag_config_snapshot=rag_config_snapshot,
        notes=(feedback.reason.strip()[:2000] if feedback.reason else None),
        created_by=account_id,
    )
    db.add(evidence_item)
    db.flush()

    audit_log_event(
        db,
        tenant_id=tenant_id,
        actor_id=account_id,
        action="evidence.item.create_from_feedback",
        resource_type="evidence_item",
        resource_id=str(evidence_item.id),
        details={
            "feedback_id": str(feedback.id),
            "message_id": str(feedback.message_id),
            "suite_id": str(suite.id),
            "dataset_id": str(suite.dataset_id),
            "rating": feedback.rating,
            "reference_sources": len(reference_sources),
        },
    )
    db.commit()
    db.refresh(evidence_item)
    return evidence_item
