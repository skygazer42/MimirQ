"""
EvidenceSuite API (enterprise ground-truth evidence workbench).

Key goals:
- Dataset-scoped evidence assets with approval lifecycle
- Reproducible snapshots (best-effort)
- Sync approved evidence into RAGAS regression cases for retrieval-only evaluation
"""

import csv
import hashlib
import io
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import Session, aliased

from app.api.dependencies import get_current_account_id, get_tenant_id
from app.api.schemas.evaluation import (
    EvidenceHardcaseDiscoveryOut,
    EvidenceHardcaseDiscoveryQuery,
    EvidenceItemCreateRequest,
    EvidenceItemImportQuery,
    EvidenceItemImportResponse,
    EvidenceItemList,
    EvidenceItemListQuery,
    EvidenceItemOut,
    EvidenceItemPatchRequest,
    EvidenceReferenceDriftAuditOut,
    EvidenceReferenceDriftAuditQuery,
    EvidenceReferenceRepairQuery,
    EvidenceReferenceRepairRequest,
    EvidenceReferenceRepairResponse,
    EvidenceSuiteCreateRequest,
    EvidenceSuiteDashboardOut,
    EvidenceSuiteDashboardQuery,
    EvidenceSuiteExportQuery,
    EvidenceSuiteExportV1,
    EvidenceSuiteList,
    EvidenceSuiteListQuery,
    EvidenceSuiteOut,
    EvidenceSuitePatchRequest,
    EvidenceSuiteSyncRegressionResponse,
    EvidenceTrainingExportQuery,
    EvidenceTrainingExportRow,
)
from app.api.utils import DEFAULT_HTTP_EXCEPTION_RESPONSES, file_response_headers
from app.core.config import settings
from app.core.database import get_db
from app.models.chat import Conversation, Message
from app.models.dataset import Dataset, DatasetPermission, DatasetPermissionEnum
from app.models.document import Document as DBDocument
from app.models.evaluation import RagasRegressionCase
from app.models.evidence import EvidenceItem, EvidenceSuite
from app.models.feedback import MessageFeedback
from app.rag.core.logging import get_logger
from app.services import dataset_service
from app.services.audit_log_service import audit_log_event
from app.services.evaluation_reference_sources import finalize_reference_sources
from app.services.evidence_dashboard import compute_suite_coverage, compute_suite_throughput
from app.services.evidence_drift_audit_service import audit_reference_sources_drift
from app.services.evidence_feedback_materialization import materialize_feedback_case, normalize_reference_sources
from app.services.evidence_item_import import parse_qa_faq_import_bytes, plan_evidence_item_import
from app.services.evidence_reference_repair_service import repair_evidence_suite_reference_sources_with_dataset
from app.services.hardcase_discovery_service import (
    build_rag_trace_index_from_records,
    plan_feedback_hardcase_candidates,
    read_jsonl_tail,
)
from app.services.rag_runtime_limiter import run_blocking_call_with_managed_session

_DETAIL_SUITE_NOT_FOUND = "Suite not found"
_DETAIL_ITEM_NOT_FOUND = "Item not found"

router = APIRouter(responses=DEFAULT_HTTP_EXCEPTION_RESPONSES)
logger = get_logger(__name__)


def _hash_text_for_metrics(text: str) -> str:
    """
    Match metrics JSONL `question_hash` (sha256[:16]) for dedupe.
    """
    raw = text.encode("utf-8", "ignore")
    return hashlib.sha256(raw).hexdigest()[:16]


def _ensure_status(item: EvidenceItem, *, expected: str) -> None:
    cur = item.status.strip().lower()
    if cur != expected:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status transition (expected {expected}, got {cur or 'unknown'})",
        )


def _empty_suite_counts() -> dict[str, int]:
    return {"total": 0, "draft": 0, "reviewed": 0, "approved": 0, "archived": 0}


def _suite_counts(db: Session, *, tenant_id: UUID, suite_ids: list[UUID]) -> dict[UUID, dict[str, int]]:
    """
    Build per-suite status counts.

    Returns: {suite_id: {"total": n, "draft": n, "reviewed": n, "approved": n, "archived": n}}
    """
    counts = {suite_id: _empty_suite_counts() for suite_id in suite_ids}
    if not suite_ids:
        return counts

    rows = (
        db.query(EvidenceItem.suite_id, EvidenceItem.status, func.count(EvidenceItem.id))
        .filter(EvidenceItem.tenant_id == tenant_id, EvidenceItem.suite_id.in_(suite_ids))
        .group_by(EvidenceItem.suite_id, EvidenceItem.status)
        .all()
    )
    for suite_id, status, count in rows:
        suite_counts = counts[suite_id]
        status = status.strip().lower()
        if status in suite_counts:
            suite_counts[status] = count
        suite_counts["total"] += count
    return counts


def _get_evidence_suite_or_404(db: Session, *, tenant_id: UUID, suite_id: UUID) -> EvidenceSuite:
    suite = db.query(EvidenceSuite).filter(EvidenceSuite.id == suite_id, EvidenceSuite.tenant_id == tenant_id).first()
    if suite is None:
        raise HTTPException(status_code=404, detail=_DETAIL_SUITE_NOT_FOUND)
    return suite


def _get_evidence_item_or_404(db: Session, *, tenant_id: UUID, item_id: UUID) -> EvidenceItem:
    row = db.query(EvidenceItem).filter(EvidenceItem.id == item_id, EvidenceItem.tenant_id == tenant_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail=_DETAIL_ITEM_NOT_FOUND)
    return row


def _assert_suite_access(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    suite: EvidenceSuite,
    writable: bool,
) -> None:
    ds = dataset_service.get_dataset(db, tenant_id, suite.dataset_id)
    if writable:
        dataset_service.assert_dataset_writable(db, ds, account_id)
        return
    dataset_service.assert_dataset_readable(db, ds, account_id)


async def _enqueue_reference_repair_job(
    *,
    tenant_id: UUID,
    suite_id: UUID,
    account_id: str,
    payload: EvidenceReferenceRepairRequest,
) -> str | None:
    from app.tasks.queue import enqueue_evidence_reference_sources_repair

    cfg = payload.model_dump()
    cfg_json = json.dumps(cfg, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    cfg_hash = hashlib.sha256(cfg_json.encode("utf-8", "ignore")).hexdigest()[:16]
    job_id = f"evidence_repair:{tenant_id}:{suite_id}:{cfg_hash}"
    return await enqueue_evidence_reference_sources_repair(
        tenant_id=tenant_id,
        suite_id=suite_id,
        requested_by=account_id,
        job_id=job_id,
        apply=payload.apply,
        allow_approved=payload.allow_approved,
        include_archived_items=payload.include_archived_items,
        max_items=payload.max_items,
        max_refs_per_item=payload.max_refs_per_item,
        max_changes=payload.max_changes,
    )


def _audit_reference_repair_enqueue(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    suite_id: UUID,
    task_id: str | None,
    payload: EvidenceReferenceRepairRequest,
) -> None:
    try:
        audit_log_event(
            db,
            tenant_id=tenant_id,
            actor_id=account_id,
            action="evidence.reference_sources.repair.enqueue",
            resource_type="evidence_suite",
            resource_id=str(suite_id),
            details={
                "async": True,
                "task_id": task_id,
                "applied": payload.apply,
                "allow_approved": payload.allow_approved,
                "include_archived_items": payload.include_archived_items,
                "max_items": payload.max_items,
                "max_refs_per_item": payload.max_refs_per_item,
                "max_changes": payload.max_changes,
            },
        )
        db.commit()
    except Exception:
        db.rollback()
        logger.warning("Reference repair enqueue audit failed", exc_info=True)


def _load_hardcase_traces(
    *,
    tenant_id: UUID,
    now: datetime,
    window_minutes: int,
    max_bytes: int,
    path_str: str,
) -> tuple[dict[str, Any], bool]:
    cutoff_ms = int(now.timestamp() * 1000) - window_minutes * 60_000
    raw_records, truncated_by_tail = read_jsonl_tail(Path(path_str), max_bytes=max_bytes)
    tenant_key = str(tenant_id)

    earliest_ts_ms: int | None = None
    for record in raw_records:
        if record.get("event") != "rag_trace":
            continue
        if record.get("tenant_id") != tenant_key:
            continue
        try:
            ts_ms = int(record.get("ts_ms"))
        except (TypeError, ValueError, OverflowError):
            continue
        if ts_ms == 0:
            continue
        if earliest_ts_ms is None or ts_ms < earliest_ts_ms:
            earliest_ts_ms = ts_ms

    trace_index = build_rag_trace_index_from_records(
        records=raw_records,
        tenant_id=tenant_key,
        cutoff_ms=cutoff_ms,
    )
    truncated = truncated_by_tail and earliest_ts_ms is not None and earliest_ts_ms > cutoff_ms
    return trace_index, truncated


def _collect_existing_suite_fingerprints(
    db: Session,
    *,
    tenant_id: UUID,
    suite_id: UUID,
    max_existing_items: int,
) -> tuple[set[str], set[str]]:
    existing_question_hashes: set[str] = set()
    existing_feedback_ids: set[str] = set()
    existing_rows = (
        db.query(EvidenceItem.query, EvidenceItem.source_metadata)
        .filter(EvidenceItem.tenant_id == tenant_id, EvidenceItem.suite_id == suite_id)
        .limit(max_existing_items)
        .all()
    )
    for query_text, metadata in existing_rows:
        if query_text.strip():
            existing_question_hashes.add(_hash_text_for_metrics(query_text.strip()))
        feedback_id = metadata.get("feedback_id")
        if feedback_id is not None:
            feedback_id = str(feedback_id).strip()
        if feedback_id:
            existing_feedback_ids.add(feedback_id)
    return existing_question_hashes, existing_feedback_ids


def _collect_hardcase_feedback_rows(
    db: Session,
    *,
    tenant_id: UUID,
    suite: EvidenceSuite,
    max_rating: int,
    cutoff_dt: datetime,
    max_feedback_rows: int,
) -> list[dict[str, Any]]:
    feedback_rows = (
        db.query(MessageFeedback, Message.message_metadata)
        .join(Message, Message.id == MessageFeedback.message_id)
        .join(Conversation, Conversation.id == MessageFeedback.conversation_id)
        .filter(
            MessageFeedback.tenant_id == tenant_id,
            Conversation.tenant_id == tenant_id,
            Message.tenant_id == tenant_id,
            Conversation.dataset_id == suite.dataset_id,
            MessageFeedback.rating <= max_rating,
            MessageFeedback.updated_at >= cutoff_dt,
        )
        .order_by(MessageFeedback.updated_at.desc())
        .limit(max_feedback_rows)
        .all()
    )

    out: list[dict[str, Any]] = []
    for feedback, meta in feedback_rows:
        message_metadata = meta if isinstance(meta, dict) else {}
        request_id = message_metadata.get("request_id")
        if request_id is not None:
            request_id = request_id.strip()
        if not request_id:
            continue
        out.append(
            {
                "feedback_id": str(feedback.id),
                "conversation_id": str(feedback.conversation_id),
                "message_id": str(feedback.message_id),
                "request_id": request_id,
                "rating": feedback.rating,
                "tags": list(feedback.tags) if isinstance(feedback.tags, list) else [],
            }
        )
    return out


def _apply_evidence_item_patch_fields(
    payload: EvidenceItemPatchRequest,
    *,
    row: EvidenceItem,
    db: Session,
    tenant_id: UUID,
    account_id: str,
    dataset_id: UUID,
) -> None:
    fields = payload.model_fields_set
    if "query" in fields and payload.query is not None:
        row.query = payload.query
    if "expected_answer" in fields:
        row.expected_answer = payload.expected_answer
    if "tags" in fields and payload.tags is not None:
        row.tags = payload.tags
    if "source_metadata" in fields and payload.source_metadata is not None:
        row.source_metadata = payload.source_metadata
    if "notes" in fields:
        row.notes = payload.notes
    if "retrieval_snapshot" in fields and payload.retrieval_snapshot is not None:
        row.retrieval_snapshot = payload.retrieval_snapshot
    if "rag_config_snapshot" in fields and payload.rag_config_snapshot is not None:
        row.rag_config_snapshot = payload.rag_config_snapshot
    if "reference_sources" not in fields or payload.reference_sources is None:
        return

    row.reference_sources = finalize_reference_sources(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=dataset_id,
        reference_sources=payload.reference_sources,
    )


def _feedback_training_export_row(
    *,
    feedback: MessageFeedback,
    assistant: Message,
    conversation: Conversation,
    trace_payload: dict[str, Any] | None,
    question: str,
    reference_sources: list[dict[str, Any]],
) -> dict[str, Any]:
    extra = dict(feedback.extra or {})
    return {
        "schema": "mimirq.training_export_row.v1",
        "source_type": "feedback",
        "source_id": str(feedback.id),
        "dataset_id": conversation.dataset_id,
        "status": "feedback",
        "question": question.strip(),
        "expected_answer": feedback.expected_answer,
        "tags": list(feedback.tags or []),
        "reference_sources": normalize_reference_sources(reference_sources),
        "trace_snapshot": dict(trace_payload) if trace_payload is not None else {},
        "rag_config_snapshot": dict(extra.get("rag_config_snapshot") or {}),
        "source_metadata": {
            "conversation_id": str(conversation.id),
            "message_id": str(assistant.id),
            "rating": feedback.rating,
            "reason": feedback.reason,
        },
        "created_at": feedback.created_at.isoformat() if feedback.created_at else None,
        "updated_at": feedback.updated_at.isoformat() if feedback.updated_at else None,
    }


def _evidence_training_export_row(item: EvidenceItem) -> dict[str, Any]:
    source_metadata = dict(item.source_metadata)
    source_metadata.setdefault("suite_id", str(item.suite_id))
    return {
        "schema": "mimirq.training_export_row.v1",
        "source_type": "evidence_item",
        "source_id": str(item.id),
        "dataset_id": item.dataset_id,
        "status": item.status,
        "question": item.query.strip(),
        "expected_answer": item.expected_answer,
        "tags": list(item.tags),
        "reference_sources": normalize_reference_sources(item.reference_sources),
        "trace_snapshot": dict(item.retrieval_snapshot or {}),
        "rag_config_snapshot": dict(item.rag_config_snapshot or {}),
        "source_metadata": source_metadata,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


def _collect_feedback_training_export_rows(
    db: Session,
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    limit: int,
) -> list[dict[str, Any]]:
    candidate_user = aliased(Message)
    user_message = aliased(Message)
    latest_user_message_id = (
        select(candidate_user.id)
        .where(
            candidate_user.tenant_id == tenant_id,
            candidate_user.conversation_id == Conversation.id,
            candidate_user.role == "user",
            candidate_user.created_at <= Message.created_at,
        )
        .order_by(candidate_user.created_at.desc(), candidate_user.id.desc())
        .limit(1)
        .correlate(Message, Conversation)
        .scalar_subquery()
    )
    rows = (
        db.query(MessageFeedback, Message, Conversation, user_message)
        .join(Message, Message.id == MessageFeedback.message_id)
        .join(Conversation, Conversation.id == MessageFeedback.conversation_id)
        .outerjoin(user_message, user_message.id == latest_user_message_id)
        .filter(
            MessageFeedback.tenant_id == tenant_id,
            Message.tenant_id == tenant_id,
            Conversation.tenant_id == tenant_id,
            Conversation.dataset_id == dataset_id,
            Message.role == "assistant",
        )
        .order_by(MessageFeedback.updated_at.desc())
        .limit(limit)
        .all()
    )

    out: list[dict[str, Any]] = []
    for feedback, assistant, conversation, preceding_user_message in rows:
        extra = dict(feedback.extra or {})
        trace_payload = extra.get("retrieval_trace") if isinstance(extra.get("retrieval_trace"), dict) else None
        materialized = materialize_feedback_case(
            feedback=feedback,
            assistant=assistant,
            conversation=conversation,
            user_message=preceding_user_message,
            trace_payload=trace_payload,
        )
        out.append(
            _feedback_training_export_row(
                feedback=feedback,
                assistant=assistant,
                conversation=conversation,
                trace_payload=trace_payload,
                question=materialized.question,
                reference_sources=materialized.reference_sources,
            )
        )
    return out


def _collect_evidence_training_export_rows(
    db: Session,
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    include_archived: bool,
    limit: int,
) -> list[dict[str, Any]]:
    items_query = db.query(EvidenceItem).filter(
        EvidenceItem.tenant_id == tenant_id, EvidenceItem.dataset_id == dataset_id
    )
    if not include_archived:
        items_query = items_query.filter(EvidenceItem.status != "archived")
    items = items_query.order_by(EvidenceItem.updated_at.desc()).limit(limit).all()
    return [_evidence_training_export_row(item) for item in items]


def _render_training_export_csv(rows: list[EvidenceTrainingExportRow]) -> str:
    buf = io.StringIO()
    fieldnames = [
        "schema",
        "source_type",
        "source_id",
        "dataset_id",
        "status",
        "question",
        "expected_answer",
        "tags_json",
        "reference_sources_json",
        "trace_snapshot_json",
        "rag_config_snapshot_json",
        "source_metadata_json",
        "created_at",
        "updated_at",
    ]
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {
                "schema": row.schema_,
                "source_type": row.source_type,
                "source_id": row.source_id,
                "dataset_id": row.dataset_id,
                "status": row.status,
                "question": row.question,
                "expected_answer": row.expected_answer,
                "tags_json": json.dumps(row.tags, ensure_ascii=False, separators=(",", ":")),
                "reference_sources_json": json.dumps(
                    row.reference_sources,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    default=str,
                ),
                "trace_snapshot_json": json.dumps(
                    row.trace_snapshot,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    default=str,
                ),
                "rag_config_snapshot_json": json.dumps(
                    row.rag_config_snapshot,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    default=str,
                ),
                "source_metadata_json": json.dumps(
                    row.source_metadata,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    default=str,
                ),
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            }
        )
    return buf.getvalue()


@router.post(
    "/suites/{suite_id}/repair-reference-sources",
    response_model=EvidenceReferenceRepairResponse,
)
async def repair_evidence_suite_reference_sources(
    suite_id: UUID,
    payload: EvidenceReferenceRepairRequest,
    response: Response,
    query: Annotated[EvidenceReferenceRepairQuery, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
) -> EvidenceReferenceRepairResponse:
    """
    Best-effort repair for drifted `reference_sources`.

    Repair strategy:
    1) (doc_pipeline_key + chunk_index) exact relink
    2) quote needle match (within active pipeline chunks when available)

    Safety:
    - Does not mutate approved items unless `allow_approved=true`.
    - Dry-run by default (`apply=false`).
    """

    def authorize_suite(worker_db: Session) -> UUID:
        dataset_service.ensure_member(worker_db, tenant_id, account_id)
        suite = _get_evidence_suite_or_404(worker_db, tenant_id=tenant_id, suite_id=suite_id)
        _assert_suite_access(
            worker_db,
            tenant_id=tenant_id,
            account_id=account_id,
            suite=suite,
            writable=payload.apply,
        )
        return suite.dataset_id

    suite_dataset_id = await run_blocking_call_with_managed_session(authorize_suite, request_db=None)

    # Optional async enqueue: run repair as a queue job (default remains synchronous for compatibility).
    if query.async_mode:
        if not settings.TASK_QUEUE_ENABLED:
            raise HTTPException(status_code=400, detail="Task queue is disabled (TASK_QUEUE_ENABLED=false)")
        try:
            task_id = await _enqueue_reference_repair_job(
                tenant_id=tenant_id,
                suite_id=suite_id,
                account_id=account_id,
                payload=payload,
            )
            await run_blocking_call_with_managed_session(
                lambda worker_db: _audit_reference_repair_enqueue(
                    worker_db,
                    tenant_id=tenant_id,
                    account_id=account_id,
                    suite_id=suite_id,
                    task_id=task_id,
                    payload=payload,
                ),
                request_db=None,
            )
            response.status_code = 202
            if task_id:
                response.headers["X-Task-Id"] = task_id
            return EvidenceReferenceRepairResponse(
                suite_id=suite_id,
                dataset_id=suite_dataset_id,
                applied=payload.apply,
            )
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=503, detail=f"Failed to enqueue repair job: {str(exc)[:200]}") from exc

    result = await run_blocking_call_with_managed_session(
        lambda worker_db: repair_evidence_suite_reference_sources_with_dataset(
            worker_db,
            tenant_id=tenant_id,
            suite_id=suite_id,
            suite_dataset_id=suite_dataset_id,
            apply=payload.apply,
            allow_approved=payload.allow_approved,
            include_archived_items=payload.include_archived_items,
            max_items=payload.max_items,
            max_refs_per_item=payload.max_refs_per_item,
            max_changes=payload.max_changes,
            actor_id=account_id,
        ),
        request_db=None,
    )
    return EvidenceReferenceRepairResponse.model_validate(result)


@router.post("/suites", response_model=EvidenceSuiteOut, status_code=201)
def create_evidence_suite(
    payload: EvidenceSuiteCreateRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> EvidenceSuiteOut:
    dataset_service.ensure_member(db, tenant_id, account_id)

    ds = dataset_service.get_dataset(db, tenant_id, payload.dataset_id)
    dataset_service.assert_dataset_writable(db, ds, account_id)

    row = EvidenceSuite(
        tenant_id=tenant_id,
        dataset_id=payload.dataset_id,
        name=payload.name,
        description=payload.description,
        tags=payload.tags,
        config=payload.config,
        created_by=account_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    out = EvidenceSuiteOut.model_validate(row)
    out.item_counts = _empty_suite_counts()
    return out


@router.get("/suites", response_model=EvidenceSuiteList)
def list_evidence_suites(
    query: Annotated[EvidenceSuiteListQuery, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> EvidenceSuiteList:
    dataset_service.ensure_member(db, tenant_id, account_id)

    suites_query = db.query(EvidenceSuite).filter(EvidenceSuite.tenant_id == tenant_id)
    if query.dataset_id is not None:
        ds = dataset_service.get_dataset(db, tenant_id, query.dataset_id)
        dataset_service.assert_dataset_readable(db, ds, account_id)
        suites_query = suites_query.filter(EvidenceSuite.dataset_id == query.dataset_id)
    else:
        # Security trimming: list only suites under datasets readable by the caller.
        allowed_dataset_ids = (
            db.query(Dataset.id)
            .filter(Dataset.tenant_id == tenant_id)
            .filter(
                or_(
                    Dataset.owner_id == account_id,
                    Dataset.permission == DatasetPermissionEnum.ALL_TEAM_MEMBERS,
                    and_(
                        Dataset.permission == DatasetPermissionEnum.PARTIAL_MEMBERS,
                        exists()
                        .where(DatasetPermission.tenant_id == tenant_id)
                        .where(DatasetPermission.dataset_id == Dataset.id)
                        .where(DatasetPermission.account_id == account_id),
                    ),
                )
            )
            .subquery()
        )
        suites_query = suites_query.filter(EvidenceSuite.dataset_id.in_(allowed_dataset_ids))
    if not query.include_archived:
        suites_query = suites_query.filter(EvidenceSuite.archived_at.is_(None))

    total = suites_query.count()
    suites = suites_query.order_by(EvidenceSuite.updated_at.desc()).offset(query.skip).limit(query.limit).all()
    suite_ids = [suite.id for suite in suites]
    counts = _suite_counts(db, tenant_id=tenant_id, suite_ids=suite_ids)

    items_out = []
    for suite in suites:
        out = EvidenceSuiteOut.model_validate(suite)
        out.item_counts = counts[suite.id]
        items_out.append(out)

    return EvidenceSuiteList(total=total, items=items_out)


@router.get("/suites/{suite_id}", response_model=EvidenceSuiteOut)
def get_evidence_suite(
    suite_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> EvidenceSuiteOut:
    dataset_service.ensure_member(db, tenant_id, account_id)

    row = _get_evidence_suite_or_404(db, tenant_id=tenant_id, suite_id=suite_id)
    _assert_suite_access(db, tenant_id=tenant_id, account_id=account_id, suite=row, writable=False)

    counts = _suite_counts(db, tenant_id=tenant_id, suite_ids=[row.id])
    out = EvidenceSuiteOut.model_validate(row)
    out.item_counts = counts[row.id]
    return out


@router.get(
    "/suites/{suite_id}/dashboard",
    response_model=EvidenceSuiteDashboardOut,
)
def get_evidence_suite_dashboard(
    suite_id: UUID,
    query: Annotated[EvidenceSuiteDashboardQuery, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> EvidenceSuiteDashboardOut:
    """
    Suite-level dashboard: status counts + slice coverage + throughput metrics.

    Coverage is derived from reference_sources by resolving referenced documents.
    """
    dataset_service.ensure_member(db, tenant_id, account_id)

    suite = _get_evidence_suite_or_404(db, tenant_id=tenant_id, suite_id=suite_id)
    _assert_suite_access(db, tenant_id=tenant_id, account_id=account_id, suite=suite, writable=False)

    # Counts: include archived so the dashboard matches suite list badges.
    counts = _suite_counts(db, tenant_id=tenant_id, suite_ids=[suite_id])
    item_counts = counts[suite_id]

    items_query = db.query(EvidenceItem).filter(EvidenceItem.tenant_id == tenant_id, EvidenceItem.suite_id == suite_id)
    if not query.include_archived_items:
        items_query = items_query.filter(EvidenceItem.status != "archived")
    items = items_query.order_by(EvidenceItem.updated_at.desc()).limit(10_000).all()

    # Resolve document slice metadata (language/file_type/quality bucket).
    doc_ids: set[UUID] = set()
    for item in items:
        refs = item.reference_sources if isinstance(item.reference_sources, list) else []
        for ref in refs:
            if not isinstance(ref, dict):
                continue
            try:
                doc_ids.add(UUID(str(ref.get("document_id"))))
            except ValueError:
                logger.debug("Skipping invalid evidence document pointer", exc_info=True)
                continue

    doc_map: dict[UUID, dict[str, Any]] = {}
    if doc_ids:
        doc_rows = (
            db.query(DBDocument.id, DBDocument.file_type, DBDocument.doc_metadata)
            .filter(DBDocument.tenant_id == tenant_id, DBDocument.id.in_(sorted(doc_ids)))
            .all()
        )
        for document_id, file_type, metadata in doc_rows:
            doc_map[document_id] = {
                "id": document_id,
                "file_type": file_type.strip().lower() or "unknown",
                "metadata": metadata if isinstance(metadata, dict) else {},
            }

    now = datetime.now(UTC)
    throughput = compute_suite_throughput(items, now=now, window_days=7)
    coverage = compute_suite_coverage(items, documents=doc_map, top_n=query.top_n, heatmap_top_n=query.heatmap_top_n)

    return EvidenceSuiteDashboardOut(
        generated_at=now,
        suite_id=suite_id,
        dataset_id=suite.dataset_id,
        item_counts=item_counts,
        coverage=coverage,
        throughput=throughput,
    )


@router.get(
    "/suites/{suite_id}/hardcase-candidates",
    response_model=EvidenceHardcaseDiscoveryOut,
)
def list_evidence_suite_hardcase_candidates(
    suite_id: UUID,
    query: Annotated[EvidenceHardcaseDiscoveryQuery, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> EvidenceHardcaseDiscoveryOut:
    """
    Discover PII-safe "hardcase" candidates for an EvidenceSuite from:
    - negative message feedback (DB)
    - recent rag_trace metrics records (JSONL)

    Output is clustered/deduped by `question_hash` and does NOT include raw query text.
    """
    dataset_service.ensure_member(db, tenant_id, account_id)

    suite = _get_evidence_suite_or_404(db, tenant_id=tenant_id, suite_id=suite_id)
    if suite.archived_at is not None:
        raise HTTPException(status_code=400, detail="Evidence suite is archived")
    _assert_suite_access(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        suite=suite,
        writable=False,
    )

    enabled = settings.ENABLE_METRICS_LOG
    path_str = settings.METRICS_LOG_PATH
    now = datetime.now(UTC)

    if not enabled:
        return EvidenceHardcaseDiscoveryOut(
            generated_at=now,
            suite_id=suite.id,
            dataset_id=suite.dataset_id,
            enabled=False,
            metrics_path=path_str,
            window_minutes=query.window_minutes,
            max_bytes=query.max_bytes,
        )

    cutoff_dt = now - timedelta(minutes=query.window_minutes)
    trace_index, truncated = _load_hardcase_traces(
        tenant_id=tenant_id,
        now=now,
        window_minutes=query.window_minutes,
        max_bytes=query.max_bytes,
        path_str=path_str,
    )

    # Compute "already in suite" fingerprints (PII-safe).
    existing_question_hashes, existing_feedback_ids = _collect_existing_suite_fingerprints(
        db,
        tenant_id=tenant_id,
        suite_id=suite_id,
        max_existing_items=5000,
    )

    # Fetch recent negative feedback (bounded).
    # Dataset-scope by conversation.dataset_id to avoid leaking cross-dataset pointers.
    feedback_rows = _collect_hardcase_feedback_rows(
        db,
        tenant_id=tenant_id,
        suite=suite,
        max_rating=query.max_rating,
        cutoff_dt=cutoff_dt,
        max_feedback_rows=query.max_feedback_rows,
    )

    candidates = plan_feedback_hardcase_candidates(
        feedback_rows=feedback_rows,
        trace_index=trace_index,
        existing_feedback_ids=existing_feedback_ids,
        existing_question_hashes=existing_question_hashes,
        max_candidates=query.max_candidates,
        include_existing=query.include_existing,
    )

    return EvidenceHardcaseDiscoveryOut(
        generated_at=now,
        suite_id=suite.id,
        dataset_id=suite.dataset_id,
        enabled=True,
        metrics_path=path_str,
        window_minutes=query.window_minutes,
        max_bytes=query.max_bytes,
        truncated=truncated,
        feedback_scanned=len(feedback_rows),
        trace_index_size=len(trace_index),
        candidates=candidates,
    )


@router.patch("/suites/{suite_id}", response_model=EvidenceSuiteOut)
def patch_evidence_suite(
    suite_id: UUID,
    payload: EvidenceSuitePatchRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> EvidenceSuiteOut:
    dataset_service.ensure_member(db, tenant_id, account_id)

    row = _get_evidence_suite_or_404(db, tenant_id=tenant_id, suite_id=suite_id)
    _assert_suite_access(db, tenant_id=tenant_id, account_id=account_id, suite=row, writable=True)

    fields = payload.model_fields_set
    if "name" in fields and payload.name is not None:
        row.name = payload.name
    if "description" in fields:
        row.description = payload.description
    if "tags" in fields and payload.tags is not None:
        row.tags = payload.tags
    if "config" in fields and payload.config is not None:
        row.config = payload.config
    if "archived_at" in fields:
        row.archived_at = payload.archived_at

    db.add(row)
    db.commit()
    db.refresh(row)

    counts = _suite_counts(db, tenant_id=tenant_id, suite_ids=[row.id])
    out = EvidenceSuiteOut.model_validate(row)
    out.item_counts = counts[row.id]
    return out


@router.get(
    "/suites/{suite_id}/drift-audit",
    response_model=EvidenceReferenceDriftAuditOut,
)
def audit_evidence_suite_reference_sources_drift(
    suite_id: UUID,
    query: Annotated[EvidenceReferenceDriftAuditQuery, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> EvidenceReferenceDriftAuditOut:
    dataset_service.ensure_member(db, tenant_id, account_id)

    suite = _get_evidence_suite_or_404(db, tenant_id=tenant_id, suite_id=suite_id)
    _assert_suite_access(db, tenant_id=tenant_id, account_id=account_id, suite=suite, writable=False)

    items_query = db.query(EvidenceItem).filter(EvidenceItem.tenant_id == tenant_id, EvidenceItem.suite_id == suite_id)
    if not query.include_archived_items:
        items_query = items_query.filter(EvidenceItem.status != "archived")
    items = items_query.order_by(EvidenceItem.updated_at.desc()).limit(5000).all()

    return audit_reference_sources_drift(
        db,
        tenant_id=tenant_id,
        dataset_id=suite.dataset_id,
        suite_id=suite_id,
        suite_dataset_id=suite.dataset_id,
        items=items,
        include_details=query.include_details,
        details_limit=query.details_limit,
        slice_top_n=query.slice_top_n,
    )


@router.get(
    "/datasets/{dataset_id}/drift-audit",
    response_model=EvidenceReferenceDriftAuditOut,
)
def audit_dataset_reference_sources_drift(
    dataset_id: UUID,
    query: Annotated[EvidenceReferenceDriftAuditQuery, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> EvidenceReferenceDriftAuditOut:
    dataset_service.ensure_member(db, tenant_id, account_id)

    ds = dataset_service.get_dataset(db, tenant_id, dataset_id)
    dataset_service.assert_dataset_readable(db, ds, account_id)

    suite_ids = [
        row[0]
        for row in (
            db.query(EvidenceSuite.id)
            .filter(
                EvidenceSuite.tenant_id == tenant_id,
                EvidenceSuite.dataset_id == dataset_id,
                EvidenceSuite.archived_at.is_(None),
            )
            .all()
        )
    ]
    if not suite_ids:
        return EvidenceReferenceDriftAuditOut(
            generated_at=datetime.now(UTC),
            dataset_id=dataset_id,
        )

    items_query = db.query(EvidenceItem).filter(
        EvidenceItem.tenant_id == tenant_id, EvidenceItem.suite_id.in_(suite_ids)
    )
    if not query.include_archived_items:
        items_query = items_query.filter(EvidenceItem.status != "archived")
    items = items_query.order_by(EvidenceItem.updated_at.desc()).limit(10_000).all()

    return audit_reference_sources_drift(
        db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        suite_id=None,
        suite_dataset_id=dataset_id,
        items=items,
        include_details=query.include_details,
        details_limit=query.details_limit,
        slice_top_n=query.slice_top_n,
    )


@router.post(
    "/suites/{suite_id}/items",
    response_model=EvidenceItemOut,
    status_code=201,
)
def create_evidence_item(
    suite_id: UUID,
    payload: EvidenceItemCreateRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> EvidenceItem:
    dataset_service.ensure_member(db, tenant_id, account_id)

    suite = _get_evidence_suite_or_404(db, tenant_id=tenant_id, suite_id=suite_id)
    if suite.archived_at is not None:
        raise HTTPException(status_code=400, detail="Suite is archived")

    if payload.suite_id != suite_id:
        raise HTTPException(status_code=400, detail="suite_id mismatch")
    if payload.dataset_id != suite.dataset_id:
        raise HTTPException(status_code=400, detail="dataset_id mismatch")

    _assert_suite_access(db, tenant_id=tenant_id, account_id=account_id, suite=suite, writable=True)

    # Normalize and validate evidence pointers before persisting.
    reference_sources = finalize_reference_sources(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=suite.dataset_id,
        reference_sources=payload.reference_sources,
    )

    row = EvidenceItem(
        tenant_id=tenant_id,
        dataset_id=suite.dataset_id,
        suite_id=suite.id,
        status="draft",
        query=payload.query,
        expected_answer=payload.expected_answer,
        tags=payload.tags,
        source_metadata=payload.source_metadata,
        reference_sources=reference_sources,
        retrieval_snapshot=payload.retrieval_snapshot,
        rag_config_snapshot=payload.rag_config_snapshot,
        notes=payload.notes,
        created_by=account_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.post(
    "/suites/{suite_id}/items/import",
    response_model=EvidenceItemImportResponse,
)
def import_evidence_items(
    suite_id: UUID,
    file: Annotated[UploadFile, File(...)],
    query: Annotated[EvidenceItemImportQuery, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> EvidenceItemImportResponse:
    """
    Import QA/FAQ rows (CSV/JSONL) as draft EvidenceItems.

    Notes:
    - Imported items are created in `draft` status.
    - reference_sources starts empty; users can later label evidence and progress review/approve.
    - Dedupes by query (query.strip(), whitespace-collapsed) within the suite.
    """
    dataset_service.ensure_member(db, tenant_id, account_id)

    suite = _get_evidence_suite_or_404(db, tenant_id=tenant_id, suite_id=suite_id)
    if suite.archived_at is not None:
        raise HTTPException(status_code=400, detail="Suite is archived")

    _assert_suite_access(db, tenant_id=tenant_id, account_id=account_id, suite=suite, writable=True)

    max_bytes = 5 * 1024 * 1024
    raw = file.file.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise HTTPException(status_code=400, detail="import file too large (max 5MB)")

    try:
        items, parse_errors = parse_qa_faq_import_bytes(
            raw=raw,
            filename=file.filename,
            max_items=query.max_items,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)[:200]) from exc

    existing_rows = (
        db.query(EvidenceItem.query)
        .filter(EvidenceItem.tenant_id == tenant_id, EvidenceItem.suite_id == suite_id)
        .all()
    )
    existing = {" ".join(query_text.split()) for (query_text,) in existing_rows}

    plan = plan_evidence_item_import(existing_queries=existing, items=items, max_items=query.max_items)
    skipped = plan["skipped"] + len(parse_errors)
    errors: list[dict[str, Any]] = list(parse_errors) + list(plan["errors"])

    for payload in plan["create_items"]:
        row = EvidenceItem(
            tenant_id=tenant_id,
            dataset_id=suite.dataset_id,
            suite_id=suite.id,
            status="draft",
            query=payload["query"].strip(),
            expected_answer=payload["expected_answer"],
            reference_sources=[],
            retrieval_snapshot={"created_from": "qa_faq_import"},
            rag_config_snapshot={},
            notes=None,
            tags=payload["tags"],
            source_metadata=payload["source_metadata"],
            created_by=account_id,
        )
        db.add(row)

    db.commit()

    return EvidenceItemImportResponse(
        suite_id=suite_id,
        dataset_id=suite.dataset_id,
        parsed=len(items),
        created=len(plan["create_items"]),
        skipped=skipped,
        errors=errors,
    )


@router.get("/suites/{suite_id}/items", response_model=EvidenceItemList)
def list_evidence_items(
    suite_id: UUID,
    query: Annotated[EvidenceItemListQuery, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> EvidenceItemList:
    dataset_service.ensure_member(db, tenant_id, account_id)

    suite = _get_evidence_suite_or_404(db, tenant_id=tenant_id, suite_id=suite_id)
    _assert_suite_access(db, tenant_id=tenant_id, account_id=account_id, suite=suite, writable=False)

    items_query = db.query(EvidenceItem).filter(EvidenceItem.tenant_id == tenant_id, EvidenceItem.suite_id == suite_id)
    if query.status:
        items_query = items_query.filter(EvidenceItem.status == query.status.strip().lower())

    total = items_query.count()
    items = items_query.order_by(EvidenceItem.updated_at.desc()).offset(query.skip).limit(query.limit).all()
    return EvidenceItemList(total=total, items=items)


@router.patch("/items/{item_id}", response_model=EvidenceItemOut)
def patch_evidence_item(
    item_id: UUID,
    payload: EvidenceItemPatchRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> EvidenceItem:
    dataset_service.ensure_member(db, tenant_id, account_id)

    row = _get_evidence_item_or_404(db, tenant_id=tenant_id, item_id=item_id)
    suite = _get_evidence_suite_or_404(db, tenant_id=tenant_id, suite_id=row.suite_id)
    _assert_suite_access(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        suite=suite,
        writable=True,
    )

    # Keep lifecycle strict: only editable in draft.
    _ensure_status(row, expected="draft")
    _apply_evidence_item_patch_fields(
        payload,
        row=row,
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=suite.dataset_id,
    )

    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.post("/items/{item_id}/review", response_model=EvidenceItemOut)
def review_evidence_item(
    item_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> EvidenceItem:
    dataset_service.ensure_member(db, tenant_id, account_id)

    row = _get_evidence_item_or_404(db, tenant_id=tenant_id, item_id=item_id)
    suite = _get_evidence_suite_or_404(db, tenant_id=tenant_id, suite_id=row.suite_id)
    _assert_suite_access(db, tenant_id=tenant_id, account_id=account_id, suite=suite, writable=True)

    _ensure_status(row, expected="draft")
    refs = row.reference_sources if isinstance(row.reference_sources, list) else []
    if not refs:
        raise HTTPException(status_code=400, detail="Cannot review item without reference_sources")
    row.status = "reviewed"
    row.reviewed_by = account_id
    row.reviewed_at = datetime.now(UTC)

    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.post("/items/{item_id}/approve", response_model=EvidenceItemOut)
def approve_evidence_item(
    item_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> EvidenceItem:
    dataset_service.ensure_member(db, tenant_id, account_id)

    row = _get_evidence_item_or_404(db, tenant_id=tenant_id, item_id=item_id)
    suite = _get_evidence_suite_or_404(db, tenant_id=tenant_id, suite_id=row.suite_id)
    _assert_suite_access(db, tenant_id=tenant_id, account_id=account_id, suite=suite, writable=True)

    _ensure_status(row, expected="reviewed")
    refs = row.reference_sources if isinstance(row.reference_sources, list) else []
    if not refs:
        raise HTTPException(status_code=400, detail="Cannot approve item without reference_sources")
    row.status = "approved"
    row.approved_by = account_id
    row.approved_at = datetime.now(UTC)

    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.post("/items/{item_id}/archive", response_model=EvidenceItemOut)
def archive_evidence_item(
    item_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> EvidenceItem:
    dataset_service.ensure_member(db, tenant_id, account_id)

    row = _get_evidence_item_or_404(db, tenant_id=tenant_id, item_id=item_id)
    suite = _get_evidence_suite_or_404(db, tenant_id=tenant_id, suite_id=row.suite_id)
    _assert_suite_access(db, tenant_id=tenant_id, account_id=account_id, suite=suite, writable=True)

    cur = row.status.strip().lower()
    if cur == "archived":
        return row

    row.status = "archived"
    row.archived_by = account_id
    row.archived_at = datetime.now(UTC)

    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.post(
    "/suites/{suite_id}/sync-regression",
    response_model=EvidenceSuiteSyncRegressionResponse,
)
def sync_suite_to_regression_cases(
    suite_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> EvidenceSuiteSyncRegressionResponse:
    dataset_service.ensure_member(db, tenant_id, account_id)

    suite = _get_evidence_suite_or_404(db, tenant_id=tenant_id, suite_id=suite_id)
    _assert_suite_access(db, tenant_id=tenant_id, account_id=account_id, suite=suite, writable=True)

    approved_items = (
        db.query(EvidenceItem)
        .filter(
            EvidenceItem.tenant_id == tenant_id,
            EvidenceItem.suite_id == suite_id,
            EvidenceItem.status == "approved",
        )
        .order_by(EvidenceItem.updated_at.desc())
        .all()
    )

    created = 0
    updated = 0
    skipped = 0
    errors: list[dict[str, Any]] = []

    for item in approved_items:
        item_id = str(item.id)
        try:
            refs = finalize_reference_sources(
                db,
                tenant_id=tenant_id,
                account_id=account_id,
                dataset_id=suite.dataset_id,
                reference_sources=item.reference_sources,
            )
            if not refs:
                skipped += 1
                continue

            tags = ["evidence_suite", f"evidence_suite:{suite_id}"]
            extra = {
                "evidence_suite_id": str(suite_id),
                "evidence_item_id": str(item.id),
            }

            case: RagasRegressionCase | None = None
            if item.regression_case_id is not None:
                case = (
                    db.query(RagasRegressionCase)
                    .filter(
                        RagasRegressionCase.id == item.regression_case_id,
                        RagasRegressionCase.tenant_id == tenant_id,
                    )
                    .first()
                )

            if case is None:
                case = RagasRegressionCase(
                    tenant_id=tenant_id,
                    dataset_id=suite.dataset_id,
                    document_ids=[],
                    question=item.query,
                    expected_answer=item.expected_answer,
                    reference_sources=refs,
                    tags=tags,
                    extra=extra,
                    created_by=account_id,
                )
                db.add(case)
                db.flush()
                item.regression_case_id = case.id
                db.add(item)
                db.commit()
                created += 1
                continue

            # Update existing case (dataset_id immutable, enforce match).
            if case.dataset_id is not None and case.dataset_id != suite.dataset_id:
                raise HTTPException(status_code=400, detail="Existing regression case dataset mismatch")

            case.question = item.query
            case.expected_answer = item.expected_answer
            case.reference_sources = refs

            existing_tags = case.tags if isinstance(case.tags, list) else []
            merged_tags = []
            seen: set[str] = set()
            for t in list(existing_tags) + tags:
                if t is None:
                    continue
                s = str(t).strip()
                if not s or s in seen:
                    continue
                seen.add(s)
                merged_tags.append(s)
            case.tags = merged_tags

            existing_extra = case.extra if isinstance(case.extra, dict) else {}
            merged_extra = dict(existing_extra)
            merged_extra.update(extra)
            case.extra = merged_extra

            db.add(case)
            db.commit()
            updated += 1
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            errors.append({"item_id": item_id, "error": str(exc)[:200]})

    return EvidenceSuiteSyncRegressionResponse(
        suite_id=suite_id,
        dataset_id=suite.dataset_id,
        created=created,
        updated=updated,
        skipped=skipped,
        errors=errors,
    )


@router.get(
    "/suites/{suite_id}/export",
    response_model=EvidenceSuiteExportV1,
)
def export_evidence_suite(
    suite_id: UUID,
    query: Annotated[EvidenceSuiteExportQuery, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> EvidenceSuiteExportV1:
    dataset_service.ensure_member(db, tenant_id, account_id)

    suite = _get_evidence_suite_or_404(db, tenant_id=tenant_id, suite_id=suite_id)
    _assert_suite_access(db, tenant_id=tenant_id, account_id=account_id, suite=suite, writable=False)

    items_query = db.query(EvidenceItem).filter(EvidenceItem.tenant_id == tenant_id, EvidenceItem.suite_id == suite_id)
    if not query.include_archived_items:
        items_query = items_query.filter(EvidenceItem.status != "archived")
    items = items_query.order_by(EvidenceItem.created_at.asc()).all()

    suite_payload = {
        "id": str(suite.id),
        "name": suite.name,
        "description": suite.description,
        "tags": list(suite.tags or []),
        "config": dict(suite.config or {}),
        "created_by": suite.created_by,
        "created_at": suite.created_at.isoformat() if suite.created_at else None,
        "updated_at": suite.updated_at.isoformat() if suite.updated_at else None,
    }
    items_payload: list[dict[str, Any]] = []
    for it in items:
        items_payload.append(
            {
                "id": str(it.id),
                "status": it.status,
                "query": it.query,
                "expected_answer": it.expected_answer,
                "tags": list(it.tags),
                "source_metadata": dict(it.source_metadata),
                "reference_sources": it.reference_sources,
                "retrieval_snapshot": it.retrieval_snapshot or {},
                "rag_config_snapshot": it.rag_config_snapshot or {},
                "notes": it.notes,
                "regression_case_id": str(it.regression_case_id) if it.regression_case_id is not None else None,
                "created_by": it.created_by,
                "reviewed_by": it.reviewed_by,
                "approved_by": it.approved_by,
                "archived_by": it.archived_by,
                "reviewed_at": it.reviewed_at.isoformat() if it.reviewed_at else None,
                "approved_at": it.approved_at.isoformat() if it.approved_at else None,
                "archived_at": it.archived_at.isoformat() if it.archived_at else None,
                "created_at": it.created_at.isoformat() if it.created_at else None,
                "updated_at": it.updated_at.isoformat() if it.updated_at else None,
            }
        )

    return EvidenceSuiteExportV1(
        exported_at=datetime.now(UTC).isoformat(),
        dataset_id=suite.dataset_id,
        suite=suite_payload,
        items=items_payload,
    )


@router.get("/training-export")
def export_training_dataset(
    query: Annotated[EvidenceTrainingExportQuery, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    """
    Export a dataset-scoped training dataset assembled from feedback + evidence.

    Output format:
    - `jsonl`: one stable row per feedback/evidence record
    - `csv`: flattened export with nested JSON columns
    """
    dataset_service.ensure_member(db, tenant_id, account_id)
    ds = dataset_service.get_dataset(db, tenant_id, query.dataset_id)
    dataset_service.assert_dataset_readable(db, ds, account_id)

    fmt = query.format.strip().lower() or "jsonl"
    if fmt not in {"jsonl", "csv"}:
        raise HTTPException(status_code=400, detail="format must be one of: jsonl, csv")
    if not query.include_feedback and not query.include_evidence:
        raise HTTPException(status_code=400, detail="at least one of include_feedback/include_evidence must be true")

    rows: list[dict[str, Any]] = []
    if query.include_feedback:
        rows.extend(
            _collect_feedback_training_export_rows(
                db,
                tenant_id=tenant_id,
                dataset_id=query.dataset_id,
                limit=query.max_rows_per_source,
            )
        )
    if query.include_evidence:
        rows.extend(
            _collect_evidence_training_export_rows(
                db,
                tenant_id=tenant_id,
                dataset_id=query.dataset_id,
                include_archived=query.include_archived_evidence,
                limit=query.max_rows_per_source,
            )
        )

    export_rows = [EvidenceTrainingExportRow.model_validate(row) for row in rows]
    export_rows.sort(
        key=lambda row: (
            row.created_at is not None,
            row.created_at,
            row.source_type,
            row.source_id,
        )
    )

    if fmt == "csv":
        content = _render_training_export_csv(export_rows)
        filename = f"dataset_{query.dataset_id}.training_export.csv"
        media_type = "text/csv"
    else:
        content = "\n".join(
            json.dumps(row.model_dump(by_alias=True), ensure_ascii=False, separators=(",", ":"), default=str)
            for row in export_rows
        )
        if content:
            content += "\n"
        filename = f"dataset_{query.dataset_id}.training_export.jsonl"
        media_type = "application/x-ndjson"

    return Response(
        content=content,
        media_type=media_type,
        headers=file_response_headers(filename),
    )
