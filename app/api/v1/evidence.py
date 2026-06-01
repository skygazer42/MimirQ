"""
EvidenceSuite API (enterprise ground-truth evidence workbench).

Key goals:
- Dataset-scoped evidence assets with approval lifecycle
- Reproducible snapshots (best-effort)
- Sync approved evidence into RAGAS regression cases for retrieval-only evaluation
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import re
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.evidence import (
    EvidenceHardcaseDiscoveryOut,
    EvidenceItemCreateRequest,
    EvidenceItemImportResponse,
    EvidenceItemList,
    EvidenceItemOut,
    EvidenceItemPatchRequest,
    EvidenceSuiteCreateRequest,
    EvidenceSuiteDashboardOut,
    EvidenceSuiteExportV1,
    EvidenceSuiteList,
    EvidenceSuiteOut,
    EvidenceSuitePatchRequest,
    EvidenceSuiteSyncRegressionResponse,
)
from app.api.schemas.evidence_audit import EvidenceReferenceDriftAuditOut
from app.api.schemas.evidence_repair import (
    EvidenceReferenceRepairRequest,
    EvidenceReferenceRepairResponse,
)
from app.api.utils.response_headers import download_response_headers
from app.core.config import settings
from app.core.database import get_db
from app.models.chat import Conversation, Message
from app.models.dataset import Dataset, DatasetPermission, DatasetPermissionEnum
from app.models.document import Document as DBDocument
from app.models.evaluation import RagasRegressionCase
from app.models.evidence import EvidenceItem, EvidenceSuite
from app.models.feedback import MessageFeedback
from app.rag.core.logging import get_logger
from app.services.audit_log_service import audit_log_event
from app.services.dataset_service import DatasetService
from app.services.hardcase_discovery_service import (
    build_rag_trace_index_from_records,
    plan_feedback_hardcase_candidates,
    read_jsonl_tail,
)
from app.services.ltr_rollout_workflow import materialize_feedback_case, normalize_reference_sources

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

_DETAIL_SUITE_NOT_FOUND = "Suite not found"
_DETAIL_ITEM_NOT_FOUND = "Item not found"

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
logger = get_logger(__name__)


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _hash_text_for_metrics(text: str) -> str:
    """
    Match metrics JSONL `question_hash` (sha256[:16]) for dedupe.
    """
    raw = (text or "").encode("utf-8", "ignore")
    return hashlib.sha256(raw).hexdigest()[:16]


def _ensure_status(item: EvidenceItem, *, expected: str) -> None:
    cur = str(getattr(item, "status", "") or "").strip().lower()
    if cur != expected:
        raise HTTPException(status_code=400, detail=f"Invalid status transition (expected {expected}, got {cur or 'unknown'})")


def _suite_counts(db: Session, *, tenant_id: UUID, suite_ids: list[UUID]) -> dict[str, dict[str, int]]:
    """
    Build per-suite status counts.

    Returns: {suite_id: {"total": n, "draft": n, "reviewed": n, "approved": n, "archived": n}}
    """
    out: dict[str, dict[str, int]] = {}
    if not suite_ids:
        return out

    rows = (
        db.query(EvidenceItem.suite_id, EvidenceItem.status, func.count(EvidenceItem.id))
        .filter(EvidenceItem.tenant_id == tenant_id, EvidenceItem.suite_id.in_(suite_ids))
        .group_by(EvidenceItem.suite_id, EvidenceItem.status)
        .all()
    )
    for suite_id, status, cnt in rows:
        sid = str(suite_id)
        st = str(status or "").strip().lower() or "unknown"
        out.setdefault(sid, {"total": 0, "draft": 0, "reviewed": 0, "approved": 0, "archived": 0})
        if st in out[sid]:
            out[sid][st] = int(cnt or 0)
        out[sid]["total"] += int(cnt or 0)

    for _sid, m in out.items():
        m.setdefault("total", sum(v for k, v in m.items() if k != "total"))
        for k in ("draft", "reviewed", "approved", "archived"):
            m.setdefault(k, 0)
    return out


def _feedback_training_export_row(
    *,
    feedback: MessageFeedback,
    assistant: Message,
    conversation: Conversation,
    trace_payload: dict[str, Any] | None,
    question: str,
    reference_sources: list[dict[str, Any]],
) -> dict[str, Any]:
    extra = dict(getattr(feedback, "extra", {}) or {})
    return {
        "schema": "mimirq.training_export_row.v1",
        "source_type": "feedback",
        "source_id": str(feedback.id),
        "dataset_id": str(getattr(conversation, "dataset_id", "") or "") or None,
        "status": "feedback",
        "question": str(question or "").strip(),
        "expected_answer": getattr(feedback, "expected_answer", None),
        "tags": list(getattr(feedback, "tags", []) or []),
        "reference_sources": normalize_reference_sources(reference_sources),
        "trace_snapshot": dict(trace_payload or {}),
        "rag_config_snapshot": dict(extra.get("rag_config_snapshot") or {}),
        "source_metadata": {
            "conversation_id": str(conversation.id),
            "message_id": str(assistant.id),
            "rating": int(getattr(feedback, "rating", 0) or 0),
            "reason": str(getattr(feedback, "reason", "") or "") or None,
        },
        "created_at": feedback.created_at.isoformat() if getattr(feedback, "created_at", None) else None,
        "updated_at": feedback.updated_at.isoformat() if getattr(feedback, "updated_at", None) else None,
    }


def _evidence_training_export_row(item: EvidenceItem) -> dict[str, Any]:
    source_metadata = dict(getattr(item, "source_metadata", {}) or {})
    source_metadata.setdefault("suite_id", str(getattr(item, "suite_id", "") or ""))
    return {
        "schema": "mimirq.training_export_row.v1",
        "source_type": "evidence_item",
        "source_id": str(item.id),
        "dataset_id": str(getattr(item, "dataset_id", "") or "") or None,
        "status": str(getattr(item, "status", "") or "").strip().lower() or None,
        "question": str(getattr(item, "query", "") or "").strip(),
        "expected_answer": getattr(item, "expected_answer", None),
        "tags": list(getattr(item, "tags", []) or []),
        "reference_sources": normalize_reference_sources(getattr(item, "reference_sources", None)),
        "trace_snapshot": dict(getattr(item, "retrieval_snapshot", {}) or {}),
        "rag_config_snapshot": dict(getattr(item, "rag_config_snapshot", {}) or {}),
        "source_metadata": source_metadata,
        "created_at": item.created_at.isoformat() if getattr(item, "created_at", None) else None,
        "updated_at": item.updated_at.isoformat() if getattr(item, "updated_at", None) else None,
    }


def _collect_feedback_training_export_rows(
    db: Session,
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    limit: int,
) -> list[dict[str, Any]]:
    rows = (
        db.query(MessageFeedback, Message, Conversation)
        .join(Message, Message.id == MessageFeedback.message_id)
        .join(Conversation, Conversation.id == MessageFeedback.conversation_id)
        .filter(
            MessageFeedback.tenant_id == tenant_id,
            Message.tenant_id == tenant_id,
            Conversation.tenant_id == tenant_id,
            Conversation.dataset_id == dataset_id,
            Message.role == "assistant",
        )
        .order_by(MessageFeedback.updated_at.desc())
        .limit(int(limit or 0))
        .all()
    )

    out: list[dict[str, Any]] = []
    for feedback, assistant, conversation in rows:
        user_message = (
            db.query(Message)
            .filter(
                Message.tenant_id == tenant_id,
                Message.conversation_id == conversation.id,
                Message.role == "user",
                Message.created_at <= assistant.created_at,
            )
            .order_by(Message.created_at.desc())
            .first()
        )
        extra = dict(getattr(feedback, "extra", {}) or {})
        trace_payload = extra.get("retrieval_trace") if isinstance(extra.get("retrieval_trace"), dict) else None
        materialized = materialize_feedback_case(
            feedback=feedback,
            assistant=assistant,
            conversation=conversation,
            user_message=user_message,
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
    q = (
        db.query(EvidenceItem)
        .filter(EvidenceItem.tenant_id == tenant_id, EvidenceItem.dataset_id == dataset_id)
        .order_by(EvidenceItem.updated_at.desc())
        .limit(int(limit or 0))
    )
    if not include_archived:
        q = q.filter(EvidenceItem.status != "archived")
    return [_evidence_training_export_row(item) for item in q.all()]


def _render_training_export_csv(rows: list[dict[str, Any]]) -> str:
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
    for row in (rows or []):
        writer.writerow(
            {
                "schema": row.get("schema"),
                "source_type": row.get("source_type"),
                "source_id": row.get("source_id"),
                "dataset_id": row.get("dataset_id"),
                "status": row.get("status"),
                "question": row.get("question"),
                "expected_answer": row.get("expected_answer"),
                "tags_json": json.dumps(row.get("tags") or [], ensure_ascii=False, separators=(",", ":")),
                "reference_sources_json": json.dumps(row.get("reference_sources") or [], ensure_ascii=False, separators=(",", ":"), default=str),
                "trace_snapshot_json": json.dumps(row.get("trace_snapshot") or {}, ensure_ascii=False, separators=(",", ":"), default=str),
                "rag_config_snapshot_json": json.dumps(row.get("rag_config_snapshot") or {}, ensure_ascii=False, separators=(",", ":"), default=str),
                "source_metadata_json": json.dumps(row.get("source_metadata") or {}, ensure_ascii=False, separators=(",", ":"), default=str),
                "created_at": row.get("created_at"),
                "updated_at": row.get("updated_at"),
            }
        )
    return buf.getvalue()


def _audit_reference_sources_drift(
    db: Session,
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    suite_id: UUID | None,
    suite_dataset_id: UUID | None,
    items: list[EvidenceItem],
    include_details: bool,
    details_limit: int,
    slice_top_n: int,
) -> EvidenceReferenceDriftAuditOut:
    """
    Audit EvidenceItem.reference_sources drift for a scope (suite or dataset).

    PII-safe: do NOT include quote/chunk content; ids + counters only.
    """
    from app.services.evidence_drift_audit_service import audit_reference_sources_drift

    return audit_reference_sources_drift(
        db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        suite_id=suite_id,
        suite_dataset_id=suite_dataset_id,
        items=items,
        include_details=bool(include_details),
        details_limit=int(details_limit or 0),
        slice_top_n=int(slice_top_n or 0),
    )


@router.post("/suites/{suite_id}/repair-reference-sources", response_model=EvidenceReferenceRepairResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def repair_evidence_suite_reference_sources(
    suite_id: UUID,
    payload: EvidenceReferenceRepairRequest,
    response: Response,
    async_mode: Annotated[bool, Query(description='Enqueue repair via task queue (arq)')] = False,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Best-effort repair for drifted `reference_sources`.

    Repair strategy:
    1) (doc_pipeline_key + chunk_index) exact relink
    2) quote needle match (within active pipeline chunks when available)

    Safety:
    - Does not mutate approved items unless `allow_approved=true`.
    - Dry-run by default (`apply=false`).
    """
    DatasetService.ensure_member(db, tenant_id, account_id)

    suite = (
        db.query(EvidenceSuite)
        .filter(EvidenceSuite.id == suite_id, EvidenceSuite.tenant_id == tenant_id)
        .first()
    )
    if not suite:
        raise HTTPException(status_code=404, detail=_DETAIL_SUITE_NOT_FOUND)

    ds = DatasetService.get_dataset(db, tenant_id, suite.dataset_id)
    if bool(payload.apply):
        DatasetService.assert_dataset_writable(db, ds, account_id)
    else:
        DatasetService.assert_dataset_readable(db, ds, account_id)

    # Optional async enqueue: run repair as a queue job (default remains synchronous for compatibility).
    if bool(async_mode):
        if not bool(getattr(settings, "TASK_QUEUE_ENABLED", False)):
            raise HTTPException(status_code=400, detail="Task queue is disabled (TASK_QUEUE_ENABLED=false)")
        try:
            from app.tasks.queue import enqueue_evidence_reference_sources_repair

            cfg = payload.model_dump()
            cfg_json = json.dumps(cfg, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            cfg_hash = hashlib.sha256(cfg_json.encode("utf-8", "ignore")).hexdigest()[:16]
            job_id = f"evidence_repair:{tenant_id}:{suite_id}:{cfg_hash}"
            task_id = await enqueue_evidence_reference_sources_repair(
                tenant_id=tenant_id,
                suite_id=suite_id,
                requested_by=account_id,
                job_id=job_id,
                apply=bool(payload.apply),
                allow_approved=bool(payload.allow_approved),
                include_archived_items=bool(payload.include_archived_items),
                max_items=int(payload.max_items or 0),
                max_refs_per_item=int(payload.max_refs_per_item or 0),
                max_changes=int(payload.max_changes or 0),
            )

            # Best-effort audit log for enqueue (PII-safe).
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
                        "task_id": str(task_id) if task_id else None,
                        "applied": bool(payload.apply),
                        "allow_approved": bool(payload.allow_approved),
                        "include_archived_items": bool(payload.include_archived_items),
                        "max_items": int(payload.max_items or 0),
                        "max_refs_per_item": int(payload.max_refs_per_item or 0),
                        "max_changes": int(payload.max_changes or 0),
                    },
                )
                db.commit()
            except Exception:
                try:
                    db.rollback()
                except Exception as exc:
                    logger.debug("Ignoring non-critical evidence router fallback failure: %s", exc)

            if response is not None:
                response.status_code = 202
                if task_id:
                    response.headers["X-Task-Id"] = str(task_id)

            return EvidenceReferenceRepairResponse(
                suite_id=suite_id,
                dataset_id=suite.dataset_id,
                applied=bool(payload.apply),
                scanned_items=0,
                scanned_references=0,
                drifted_references=0,
                repaired_references=0,
                skipped_approved_items=0,
                skipped_archived_items=0,
                changes_truncated=False,
                changes=[],
            )
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=503, detail=f"Failed to enqueue repair job: {str(exc)[:200]}") from exc

    from app.services.evidence_reference_repair_service import (
        repair_evidence_suite_reference_sources_with_dataset,
    )

    result = repair_evidence_suite_reference_sources_with_dataset(
        db,
        tenant_id=tenant_id,
        suite_id=suite_id,
        suite_dataset_id=suite.dataset_id,
        apply=bool(payload.apply),
        allow_approved=bool(payload.allow_approved),
        include_archived_items=bool(payload.include_archived_items),
        max_items=int(payload.max_items or 0),
        max_refs_per_item=int(payload.max_refs_per_item or 0),
        max_changes=int(payload.max_changes or 0),
        actor_id=account_id,
    )
    return EvidenceReferenceRepairResponse(**result)


@router.post("/suites", response_model=EvidenceSuiteOut, status_code=201, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def create_evidence_suite(
    payload: EvidenceSuiteCreateRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    DatasetService.ensure_member(db, tenant_id, account_id)

    ds = DatasetService.get_dataset(db, tenant_id, payload.dataset_id)
    DatasetService.assert_dataset_writable(db, ds, account_id)

    row = EvidenceSuite(
        tenant_id=tenant_id,
        dataset_id=payload.dataset_id,
        name=payload.name,
        description=payload.description,
        tags=list(payload.tags or []),
        config=dict(payload.config or {}),
        created_by=account_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    out = EvidenceSuiteOut.model_validate(row).model_dump()
    out["item_counts"] = {"total": 0, "draft": 0, "reviewed": 0, "approved": 0, "archived": 0}
    return out


@router.get("/suites", response_model=EvidenceSuiteList, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def list_evidence_suites(
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    dataset_id: UUID | None = None,
    include_archived: bool = False,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    DatasetService.ensure_member(db, tenant_id, account_id)

    q = db.query(EvidenceSuite).filter(EvidenceSuite.tenant_id == tenant_id)
    if dataset_id is not None:
        ds = DatasetService.get_dataset(db, tenant_id, dataset_id)
        DatasetService.assert_dataset_readable(db, ds, account_id)
        q = q.filter(EvidenceSuite.dataset_id == dataset_id)
    else:
        # Security trimming: list only suites under datasets readable by the caller.
        from sqlalchemy import and_, exists, or_  # noqa: WPS433

        allowed_ds = (
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
        q = q.filter(EvidenceSuite.dataset_id.in_(allowed_ds))
    if not include_archived:
        q = q.filter(EvidenceSuite.archived_at.is_(None))

    total = q.count()
    suites = q.order_by(EvidenceSuite.updated_at.desc()).offset(skip).limit(limit).all()
    suite_ids = [s.id for s in suites if s and s.id]
    counts = _suite_counts(db, tenant_id=tenant_id, suite_ids=suite_ids)

    items_out: list[dict[str, Any]] = []
    for s in suites:
        out = EvidenceSuiteOut.model_validate(s).model_dump()
        out["item_counts"] = counts.get(str(s.id)) or {"total": 0, "draft": 0, "reviewed": 0, "approved": 0, "archived": 0}
        items_out.append(out)

    return {"total": total, "items": items_out}


@router.get("/suites/{suite_id}", response_model=EvidenceSuiteOut, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def get_evidence_suite(
    suite_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    DatasetService.ensure_member(db, tenant_id, account_id)

    row = (
        db.query(EvidenceSuite)
        .filter(EvidenceSuite.id == suite_id, EvidenceSuite.tenant_id == tenant_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail=_DETAIL_SUITE_NOT_FOUND)

    ds = DatasetService.get_dataset(db, tenant_id, row.dataset_id)
    DatasetService.assert_dataset_readable(db, ds, account_id)

    counts = _suite_counts(db, tenant_id=tenant_id, suite_ids=[row.id])
    out = EvidenceSuiteOut.model_validate(row).model_dump()
    out["item_counts"] = counts.get(str(row.id)) or {"total": 0, "draft": 0, "reviewed": 0, "approved": 0, "archived": 0}
    return out


@router.get("/suites/{suite_id}/dashboard", response_model=EvidenceSuiteDashboardOut, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def get_evidence_suite_dashboard(
    suite_id: UUID,
    include_archived_items: bool = False,
    top_n: Annotated[int, Query(ge=1, le=50)] = 12,
    heatmap_top_n: Annotated[int, Query(ge=2, le=20)] = 8,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Suite-level dashboard: status counts + slice coverage + throughput metrics.

    Coverage is derived from reference_sources by resolving referenced documents.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)

    suite = (
        db.query(EvidenceSuite)
        .filter(EvidenceSuite.id == suite_id, EvidenceSuite.tenant_id == tenant_id)
        .first()
    )
    if not suite:
        raise HTTPException(status_code=404, detail=_DETAIL_SUITE_NOT_FOUND)

    ds = DatasetService.get_dataset(db, tenant_id, suite.dataset_id)
    DatasetService.assert_dataset_readable(db, ds, account_id)

    # Counts: include archived so the dashboard matches suite list badges.
    counts = _suite_counts(db, tenant_id=tenant_id, suite_ids=[suite_id])
    item_counts = counts.get(str(suite_id)) or {"total": 0, "draft": 0, "reviewed": 0, "approved": 0, "archived": 0}

    q = db.query(EvidenceItem).filter(EvidenceItem.tenant_id == tenant_id, EvidenceItem.suite_id == suite_id)
    if not include_archived_items:
        q = q.filter(EvidenceItem.status != "archived")
    items = q.order_by(EvidenceItem.updated_at.desc()).limit(10_000).all()

    # Resolve document slice metadata (language/file_type/quality bucket).
    doc_ids: set[UUID] = set()
    for it in items:
        refs = it.reference_sources if isinstance(getattr(it, "reference_sources", None), list) else []
        for ref in refs:
            if not isinstance(ref, dict):
                continue
            try:
                doc_ids.add(UUID(str(ref.get("document_id"))))
            except Exception:
                logging.getLogger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
                continue

    doc_map: dict[UUID, dict[str, Any]] = {}
    if doc_ids:
        doc_rows = (
            db.query(DBDocument.id, DBDocument.file_type, DBDocument.doc_metadata)
            .filter(DBDocument.tenant_id == tenant_id, DBDocument.id.in_(sorted(doc_ids)))
            .all()
        )
        for did, ft, meta in doc_rows:
            if did is None:
                continue
            doc_map[did] = {
                "id": did,
                "file_type": str(ft or "").strip().lower() or "unknown",
                "metadata": meta if isinstance(meta, dict) else {},
            }

    from app.services.evidence_dashboard import compute_suite_coverage, compute_suite_throughput  # noqa: WPS433

    now = _now_utc()
    throughput = compute_suite_throughput(items, now=now, window_days=7)
    coverage = compute_suite_coverage(items, documents=doc_map, top_n=int(top_n), heatmap_top_n=int(heatmap_top_n))

    return EvidenceSuiteDashboardOut(
        generated_at=now,
        suite_id=suite_id,
        dataset_id=suite.dataset_id,
        item_counts=item_counts,
        coverage=coverage,
        throughput=throughput,
    )


@router.get("/suites/{suite_id}/hardcase-candidates", response_model=EvidenceHardcaseDiscoveryOut, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def list_evidence_suite_hardcase_candidates(
    suite_id: UUID,
    window_minutes: Annotated[int, Query(ge=1, le=60 * 24 * 30)] = 7 * 24 * 60,
    max_bytes: Annotated[int, Query(ge=100000, le=50000000)] = 10_000_000,
    max_feedback_rows: Annotated[int, Query(ge=1, le=5000)] = 500,
    max_candidates: Annotated[int, Query(ge=0, le=200)] = 50,
    max_rating: Annotated[int, Query(ge=1, le=5)] = 2,
    include_existing: bool = False,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Discover PII-safe "hardcase" candidates for an EvidenceSuite from:
    - negative message feedback (DB)
    - recent rag_trace metrics records (JSONL)

    Output is clustered/deduped by `question_hash` and does NOT include raw query text.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)

    suite = (
        db.query(EvidenceSuite)
        .filter(EvidenceSuite.id == suite_id, EvidenceSuite.tenant_id == tenant_id)
        .first()
    )
    if not suite:
        raise HTTPException(status_code=404, detail=_DETAIL_SUITE_NOT_FOUND)
    if getattr(suite, "archived_at", None) is not None:
        raise HTTPException(status_code=400, detail="Evidence suite is archived")

    ds = DatasetService.get_dataset(db, tenant_id, suite.dataset_id)
    DatasetService.assert_dataset_readable(db, ds, account_id)

    enabled = bool(getattr(settings, "ENABLE_METRICS_LOG", False))
    path_str = str(getattr(settings, "METRICS_LOG_PATH", "./logs/rag_metrics.jsonl") or "./logs/rag_metrics.jsonl")
    now = _now_utc()

    if not enabled:
        return EvidenceHardcaseDiscoveryOut(
            generated_at=now,
            suite_id=suite.id,
            dataset_id=suite.dataset_id,
            enabled=False,
            metrics_path=path_str,
            window_minutes=int(window_minutes),
            max_bytes=int(max_bytes),
            truncated=False,
            feedback_scanned=0,
            trace_index_size=0,
            candidates=[],
        )

    cutoff_ms = int(now.timestamp() * 1000) - (int(window_minutes) * 60_000)
    cutoff_dt = now - timedelta(minutes=int(window_minutes))

    # 1) Load recent trace summaries (bounded).
    raw_records, truncated_by_tail = read_jsonl_tail(Path(path_str), max_bytes=int(max_bytes or 0))
    tenant_key = str(tenant_id)

    earliest_ts_ms: int | None = None
    for r in raw_records:
        if str(r.get("event") or "") != "rag_trace":
            continue
        if str(r.get("tenant_id") or "") != tenant_key:
            continue
        try:
            ts_ms = int(r.get("ts_ms") or 0)
        except Exception:
            ts_ms = 0
        if not ts_ms:
            continue
        if earliest_ts_ms is None or ts_ms < earliest_ts_ms:
            earliest_ts_ms = ts_ms
    truncated = bool(truncated_by_tail and earliest_ts_ms is not None and earliest_ts_ms > cutoff_ms)

    trace_index = build_rag_trace_index_from_records(
        records=raw_records,
        tenant_id=tenant_key,
        cutoff_ms=cutoff_ms,
    )

    # 2) Compute "already in suite" fingerprints (PII-safe).
    max_existing_items = 5000
    existing_question_hashes: set[str] = set()
    existing_feedback_ids: set[str] = set()
    existing_rows = (
        db.query(EvidenceItem.query, EvidenceItem.source_metadata)
        .filter(EvidenceItem.tenant_id == tenant_id, EvidenceItem.suite_id == suite_id)
        .limit(max_existing_items)
        .all()
    )
    for q, meta in existing_rows:
        if isinstance(q, str) and q.strip():
            existing_question_hashes.add(_hash_text_for_metrics(q.strip()))
        if isinstance(meta, dict):
            fid = str(meta.get("feedback_id") or "").strip()
            if fid:
                existing_feedback_ids.add(fid)

    # 3) Fetch recent negative feedback (bounded).
    # Dataset-scope by conversation.dataset_id to avoid leaking cross-dataset pointers.
    fb_rows = (
        db.query(MessageFeedback, Message.message_metadata)
        .join(Message, Message.id == MessageFeedback.message_id)
        .join(Conversation, Conversation.id == MessageFeedback.conversation_id)
        .filter(
            MessageFeedback.tenant_id == tenant_id,
            Conversation.tenant_id == tenant_id,
            Message.tenant_id == tenant_id,
            Conversation.dataset_id == suite.dataset_id,
            MessageFeedback.rating <= int(max_rating),
            MessageFeedback.updated_at >= cutoff_dt,
        )
        .order_by(MessageFeedback.updated_at.desc())
        .limit(int(max_feedback_rows))
        .all()
    )

    feedback_rows: list[dict[str, Any]] = []
    for fb, meta in fb_rows:
        mm = meta if isinstance(meta, dict) else {}
        request_id = str(mm.get("request_id") or "").strip()
        if not request_id:
            continue
        feedback_rows.append(
            {
                "feedback_id": str(fb.id),
                "conversation_id": str(fb.conversation_id),
                "message_id": str(fb.message_id),
                "request_id": request_id,
                "rating": int(getattr(fb, "rating", 0) or 0),
                "tags": list(getattr(fb, "tags", []) or []) if isinstance(getattr(fb, "tags", None), list) else [],
            }
        )

    candidates = plan_feedback_hardcase_candidates(
        feedback_rows=feedback_rows,
        trace_index=trace_index,
        existing_feedback_ids=existing_feedback_ids,
        existing_question_hashes=existing_question_hashes,
        max_candidates=int(max_candidates),
        include_existing=bool(include_existing),
    )

    return EvidenceHardcaseDiscoveryOut(
        generated_at=now,
        suite_id=suite.id,
        dataset_id=suite.dataset_id,
        enabled=True,
        metrics_path=path_str,
        window_minutes=int(window_minutes),
        max_bytes=int(max_bytes),
        truncated=truncated,
        feedback_scanned=int(len(feedback_rows)),
        trace_index_size=int(len(trace_index)),
        candidates=candidates,
    )


@router.patch("/suites/{suite_id}", response_model=EvidenceSuiteOut, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def patch_evidence_suite(
    suite_id: UUID,
    payload: EvidenceSuitePatchRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    DatasetService.ensure_member(db, tenant_id, account_id)

    row = (
        db.query(EvidenceSuite)
        .filter(EvidenceSuite.id == suite_id, EvidenceSuite.tenant_id == tenant_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail=_DETAIL_SUITE_NOT_FOUND)

    ds = DatasetService.get_dataset(db, tenant_id, row.dataset_id)
    DatasetService.assert_dataset_writable(db, ds, account_id)

    fields = set(getattr(payload, "model_fields_set", set()) or set())
    if "name" in fields and payload.name is not None:
        row.name = payload.name
    if "description" in fields:
        row.description = payload.description
    if "tags" in fields and payload.tags is not None:
        row.tags = list(payload.tags or [])
    if "config" in fields and payload.config is not None:
        row.config = dict(payload.config or {})
    if "archived_at" in fields:
        row.archived_at = payload.archived_at

    db.add(row)
    db.commit()
    db.refresh(row)

    counts = _suite_counts(db, tenant_id=tenant_id, suite_ids=[row.id])
    out = EvidenceSuiteOut.model_validate(row).model_dump()
    out["item_counts"] = counts.get(str(row.id)) or {"total": 0, "draft": 0, "reviewed": 0, "approved": 0, "archived": 0}
    return out


@router.get("/suites/{suite_id}/drift-audit", response_model=EvidenceReferenceDriftAuditOut, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def audit_evidence_suite_reference_sources_drift(
    suite_id: UUID,
    include_archived_items: bool = False,
    include_details: bool = True,
    details_limit: Annotated[int, Query(ge=0, le=2000)] = 200,
    slice_top_n: Annotated[int, Query(ge=1, le=200)] = 20,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    DatasetService.ensure_member(db, tenant_id, account_id)

    suite = (
        db.query(EvidenceSuite)
        .filter(EvidenceSuite.id == suite_id, EvidenceSuite.tenant_id == tenant_id)
        .first()
    )
    if not suite:
        raise HTTPException(status_code=404, detail=_DETAIL_SUITE_NOT_FOUND)

    ds = DatasetService.get_dataset(db, tenant_id, suite.dataset_id)
    DatasetService.assert_dataset_readable(db, ds, account_id)

    q = db.query(EvidenceItem).filter(EvidenceItem.tenant_id == tenant_id, EvidenceItem.suite_id == suite_id)
    if not include_archived_items:
        q = q.filter(EvidenceItem.status != "archived")
    items = q.order_by(EvidenceItem.updated_at.desc()).limit(5000).all()

    return _audit_reference_sources_drift(
        db,
        tenant_id=tenant_id,
        dataset_id=suite.dataset_id,
        suite_id=suite_id,
        suite_dataset_id=suite.dataset_id,
        items=items,
        include_details=bool(include_details),
        details_limit=int(details_limit or 0),
        slice_top_n=int(slice_top_n or 0),
    )


@router.get("/datasets/{dataset_id}/drift-audit", response_model=EvidenceReferenceDriftAuditOut, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def audit_dataset_reference_sources_drift(
    dataset_id: UUID,
    include_archived_items: bool = False,
    include_details: bool = True,
    details_limit: Annotated[int, Query(ge=0, le=2000)] = 200,
    slice_top_n: Annotated[int, Query(ge=1, le=200)] = 20,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    DatasetService.ensure_member(db, tenant_id, account_id)

    ds = DatasetService.get_dataset(db, tenant_id, dataset_id)
    DatasetService.assert_dataset_readable(db, ds, account_id)

    suite_ids = [
        row[0]
        for row in (
            db.query(EvidenceSuite.id)
            .filter(EvidenceSuite.tenant_id == tenant_id, EvidenceSuite.dataset_id == dataset_id, EvidenceSuite.archived_at.is_(None))
            .all()
        )
        if row and row[0] is not None
    ]
    if not suite_ids:
        return EvidenceReferenceDriftAuditOut(
            generated_at=_now_utc(),
            dataset_id=dataset_id,
            suite_id=None,
            total_items=0,
            total_references=0,
            ok_references=0,
            drift_references=0,
            drift_rate=0.0,
            reasons={},
            slices={},
            details_truncated=False,
            drifted_references=[],
        )

    q = db.query(EvidenceItem).filter(EvidenceItem.tenant_id == tenant_id, EvidenceItem.suite_id.in_(suite_ids))
    if not include_archived_items:
        q = q.filter(EvidenceItem.status != "archived")
    items = q.order_by(EvidenceItem.updated_at.desc()).limit(10_000).all()

    return _audit_reference_sources_drift(
        db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        suite_id=None,
        suite_dataset_id=dataset_id,
        items=items,
        include_details=bool(include_details),
        details_limit=int(details_limit or 0),
        slice_top_n=int(slice_top_n or 0),
    )


@router.post("/suites/{suite_id}/items", response_model=EvidenceItemOut, status_code=201, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def create_evidence_item(
    suite_id: UUID,
    payload: EvidenceItemCreateRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    DatasetService.ensure_member(db, tenant_id, account_id)

    suite = (
        db.query(EvidenceSuite)
        .filter(EvidenceSuite.id == suite_id, EvidenceSuite.tenant_id == tenant_id)
        .first()
    )
    if not suite:
        raise HTTPException(status_code=404, detail=_DETAIL_SUITE_NOT_FOUND)
    if suite.archived_at is not None:
        raise HTTPException(status_code=400, detail="Suite is archived")

    if payload.suite_id != suite_id:
        raise HTTPException(status_code=400, detail="suite_id mismatch")
    if payload.dataset_id != suite.dataset_id:
        raise HTTPException(status_code=400, detail="dataset_id mismatch")

    ds = DatasetService.get_dataset(db, tenant_id, suite.dataset_id)
    DatasetService.assert_dataset_writable(db, ds, account_id)

    # Normalize and validate evidence pointers before persisting.
    from app.api.v1.evaluations import _finalize_reference_sources  # noqa: WPS433

    reference_sources = _finalize_reference_sources(
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
        tags=list(payload.tags or []),
        source_metadata=dict(payload.source_metadata or {}),
        reference_sources=reference_sources,
        retrieval_snapshot=dict(payload.retrieval_snapshot or {}),
        rag_config_snapshot=dict(payload.rag_config_snapshot or {}),
        notes=payload.notes,
        created_by=account_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.post("/suites/{suite_id}/items/import", response_model=EvidenceItemImportResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def import_evidence_items(
    suite_id: UUID,
    file: Annotated[UploadFile, File(...)],
    max_items: Annotated[int, Query(ge=1, le=10000)] = 2000,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Import QA/FAQ rows (CSV/JSONL) as draft EvidenceItems.

    Notes:
    - Imported items are created in `draft` status.
    - reference_sources starts empty; users can later label evidence and progress review/approve.
    - Dedupes by query (query.strip(), whitespace-collapsed) within the suite.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)

    suite = (
        db.query(EvidenceSuite)
        .filter(EvidenceSuite.id == suite_id, EvidenceSuite.tenant_id == tenant_id)
        .first()
    )
    if not suite:
        raise HTTPException(status_code=404, detail=_DETAIL_SUITE_NOT_FOUND)
    if suite.archived_at is not None:
        raise HTTPException(status_code=400, detail="Suite is archived")

    ds = DatasetService.get_dataset(db, tenant_id, suite.dataset_id)
    DatasetService.assert_dataset_writable(db, ds, account_id)

    max_bytes = 5 * 1024 * 1024
    raw = await file.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise HTTPException(status_code=400, detail="import file too large (max 5MB)")

    from app.services.evidence_item_import import parse_qa_faq_import_bytes, plan_evidence_item_import  # noqa: WPS433

    try:
        items, parse_errors = parse_qa_faq_import_bytes(raw=raw, filename=getattr(file, "filename", None), max_items=int(max_items))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)[:200]) from exc

    def _norm(s: Any) -> str:
        return " ".join(str(s or "").strip().split())

    existing_rows = (
        db.query(EvidenceItem.query)
        .filter(EvidenceItem.tenant_id == tenant_id, EvidenceItem.suite_id == suite_id)
        .all()
    )
    existing = {_norm(r[0]) for r in existing_rows if r and r[0] is not None}

    plan = plan_evidence_item_import(existing_queries=existing, items=items, max_items=int(max_items))
    created = 0
    skipped = int(plan.get("skipped") or 0) + int(len(parse_errors))
    errors: list[dict[str, Any]] = list(parse_errors or []) + list(plan.get("errors") or [])

    for payload in plan.get("create_items") or []:
        try:
            row = EvidenceItem(
                tenant_id=tenant_id,
                dataset_id=suite.dataset_id,
                suite_id=suite.id,
                status="draft",
                query=str(payload.get("query") or "").strip(),
                expected_answer=payload.get("expected_answer"),
                reference_sources=[],
                retrieval_snapshot={"created_from": "qa_faq_import"},
                rag_config_snapshot={},
                notes=None,
                tags=list(payload.get("tags") or []),
                source_metadata=dict(payload.get("source_metadata") or {}),
                created_by=account_id,
            )
            db.add(row)
            created += 1
        except Exception as exc:  # noqa: BLE001
            skipped += 1
            errors.append({"query": payload.get("query"), "error": str(exc)[:200]})

    db.commit()

    return EvidenceItemImportResponse(
        suite_id=suite_id,
        dataset_id=suite.dataset_id,
        parsed=int(len(items)),
        created=int(created),
        skipped=int(skipped),
        errors=errors,
    )


@router.get("/suites/{suite_id}/items", response_model=EvidenceItemList, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def list_evidence_items(
    suite_id: UUID,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    status: str | None = None,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    DatasetService.ensure_member(db, tenant_id, account_id)

    suite = (
        db.query(EvidenceSuite)
        .filter(EvidenceSuite.id == suite_id, EvidenceSuite.tenant_id == tenant_id)
        .first()
    )
    if not suite:
        raise HTTPException(status_code=404, detail=_DETAIL_SUITE_NOT_FOUND)

    ds = DatasetService.get_dataset(db, tenant_id, suite.dataset_id)
    DatasetService.assert_dataset_readable(db, ds, account_id)

    q = (
        db.query(EvidenceItem)
        .filter(EvidenceItem.tenant_id == tenant_id, EvidenceItem.suite_id == suite_id)
    )
    if status:
        q = q.filter(EvidenceItem.status == str(status).strip().lower())

    total = q.count()
    items = q.order_by(EvidenceItem.updated_at.desc()).offset(skip).limit(limit).all()
    return {"total": total, "items": items}


@router.patch("/items/{item_id}", response_model=EvidenceItemOut, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def patch_evidence_item(
    item_id: UUID,
    payload: EvidenceItemPatchRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    DatasetService.ensure_member(db, tenant_id, account_id)

    row = (
        db.query(EvidenceItem)
        .filter(EvidenceItem.id == item_id, EvidenceItem.tenant_id == tenant_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail=_DETAIL_ITEM_NOT_FOUND)

    suite = (
        db.query(EvidenceSuite)
        .filter(EvidenceSuite.id == row.suite_id, EvidenceSuite.tenant_id == tenant_id)
        .first()
    )
    if not suite:
        raise HTTPException(status_code=404, detail=_DETAIL_SUITE_NOT_FOUND)

    ds = DatasetService.get_dataset(db, tenant_id, suite.dataset_id)
    DatasetService.assert_dataset_writable(db, ds, account_id)

    # Keep lifecycle strict: only editable in draft.
    _ensure_status(row, expected="draft")

    fields = set(getattr(payload, "model_fields_set", set()) or set())
    if "query" in fields and payload.query is not None:
        row.query = payload.query
    if "expected_answer" in fields:
        row.expected_answer = payload.expected_answer
    if "tags" in fields and payload.tags is not None:
        row.tags = list(payload.tags or [])
    if "source_metadata" in fields and payload.source_metadata is not None:
        row.source_metadata = dict(payload.source_metadata or {})
    if "notes" in fields:
        row.notes = payload.notes
    if "retrieval_snapshot" in fields and payload.retrieval_snapshot is not None:
        row.retrieval_snapshot = dict(payload.retrieval_snapshot or {})
    if "rag_config_snapshot" in fields and payload.rag_config_snapshot is not None:
        row.rag_config_snapshot = dict(payload.rag_config_snapshot or {})
    if "reference_sources" in fields and payload.reference_sources is not None:
        from app.api.v1.evaluations import _finalize_reference_sources  # noqa: WPS433

        row.reference_sources = _finalize_reference_sources(
            db,
            tenant_id=tenant_id,
            account_id=account_id,
            dataset_id=suite.dataset_id,
            reference_sources=payload.reference_sources,
        )

    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.post("/items/{item_id}/review", response_model=EvidenceItemOut, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def review_evidence_item(
    item_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    DatasetService.ensure_member(db, tenant_id, account_id)

    row = (
        db.query(EvidenceItem)
        .filter(EvidenceItem.id == item_id, EvidenceItem.tenant_id == tenant_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail=_DETAIL_ITEM_NOT_FOUND)

    suite = (
        db.query(EvidenceSuite)
        .filter(EvidenceSuite.id == row.suite_id, EvidenceSuite.tenant_id == tenant_id)
        .first()
    )
    if not suite:
        raise HTTPException(status_code=404, detail=_DETAIL_SUITE_NOT_FOUND)

    ds = DatasetService.get_dataset(db, tenant_id, suite.dataset_id)
    DatasetService.assert_dataset_writable(db, ds, account_id)

    _ensure_status(row, expected="draft")
    refs = row.reference_sources if isinstance(getattr(row, "reference_sources", None), list) else []
    if not refs:
        raise HTTPException(status_code=400, detail="Cannot review item without reference_sources")
    row.status = "reviewed"
    row.reviewed_by = account_id
    row.reviewed_at = _now_utc()

    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.post("/items/{item_id}/approve", response_model=EvidenceItemOut, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def approve_evidence_item(
    item_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    DatasetService.ensure_member(db, tenant_id, account_id)

    row = (
        db.query(EvidenceItem)
        .filter(EvidenceItem.id == item_id, EvidenceItem.tenant_id == tenant_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail=_DETAIL_ITEM_NOT_FOUND)

    suite = (
        db.query(EvidenceSuite)
        .filter(EvidenceSuite.id == row.suite_id, EvidenceSuite.tenant_id == tenant_id)
        .first()
    )
    if not suite:
        raise HTTPException(status_code=404, detail=_DETAIL_SUITE_NOT_FOUND)

    ds = DatasetService.get_dataset(db, tenant_id, suite.dataset_id)
    DatasetService.assert_dataset_writable(db, ds, account_id)

    _ensure_status(row, expected="reviewed")
    refs = row.reference_sources if isinstance(getattr(row, "reference_sources", None), list) else []
    if not refs:
        raise HTTPException(status_code=400, detail="Cannot approve item without reference_sources")
    row.status = "approved"
    row.approved_by = account_id
    row.approved_at = _now_utc()

    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.post("/items/{item_id}/archive", response_model=EvidenceItemOut, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def archive_evidence_item(
    item_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    DatasetService.ensure_member(db, tenant_id, account_id)

    row = (
        db.query(EvidenceItem)
        .filter(EvidenceItem.id == item_id, EvidenceItem.tenant_id == tenant_id)
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail=_DETAIL_ITEM_NOT_FOUND)

    suite = (
        db.query(EvidenceSuite)
        .filter(EvidenceSuite.id == row.suite_id, EvidenceSuite.tenant_id == tenant_id)
        .first()
    )
    if not suite:
        raise HTTPException(status_code=404, detail=_DETAIL_SUITE_NOT_FOUND)

    ds = DatasetService.get_dataset(db, tenant_id, suite.dataset_id)
    DatasetService.assert_dataset_writable(db, ds, account_id)

    cur = str(getattr(row, "status", "") or "").strip().lower()
    if cur == "archived":
        return row

    row.status = "archived"
    row.archived_by = account_id
    row.archived_at = _now_utc()

    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.post("/suites/{suite_id}/sync-regression", response_model=EvidenceSuiteSyncRegressionResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def sync_suite_to_regression_cases(
    suite_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    DatasetService.ensure_member(db, tenant_id, account_id)

    suite = (
        db.query(EvidenceSuite)
        .filter(EvidenceSuite.id == suite_id, EvidenceSuite.tenant_id == tenant_id)
        .first()
    )
    if not suite:
        raise HTTPException(status_code=404, detail=_DETAIL_SUITE_NOT_FOUND)

    ds = DatasetService.get_dataset(db, tenant_id, suite.dataset_id)
    DatasetService.assert_dataset_writable(db, ds, account_id)

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

    from app.api.v1.evaluations import _finalize_reference_sources  # noqa: WPS433

    created = 0
    updated = 0
    skipped = 0
    errors: list[dict[str, Any]] = []

    for item in approved_items:
        try:
            refs = _finalize_reference_sources(
                db,
                tenant_id=tenant_id,
                account_id=account_id,
                dataset_id=suite.dataset_id,
                reference_sources=list(item.reference_sources or []),
            )
            if not refs:
                skipped += 1
                continue

            tags = ["evidence_suite", f"evidence_suite:{str(suite_id)}"]
            extra = {
                "evidence_suite_id": str(suite_id),
                "evidence_item_id": str(item.id),
            }

            case: RagasRegressionCase | None = None
            if item.regression_case_id:
                case = (
                    db.query(RagasRegressionCase)
                    .filter(RagasRegressionCase.id == item.regression_case_id, RagasRegressionCase.tenant_id == tenant_id)
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
                db.commit()
                db.refresh(case)
                item.regression_case_id = case.id
                db.add(item)
                db.commit()
                created += 1
                continue

            # Update existing case (dataset_id immutable, enforce match).
            if case.dataset_id is not None and UUID(str(case.dataset_id)) != suite.dataset_id:
                raise HTTPException(status_code=400, detail="Existing regression case dataset mismatch")

            case.question = item.query
            case.expected_answer = item.expected_answer
            case.reference_sources = refs

            existing_tags = case.tags if isinstance(case.tags, list) else []
            merged_tags = []
            seen: set[str] = set()
            for t in list(existing_tags) + tags:
                s = str(t or "").strip()
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
            errors.append({"item_id": str(item.id), "error": str(exc)[:200]})

    return EvidenceSuiteSyncRegressionResponse(
        suite_id=suite_id,
        dataset_id=suite.dataset_id,
        created=created,
        updated=updated,
        skipped=skipped,
        errors=errors,
    )


@router.get("/suites/{suite_id}/export", response_model=EvidenceSuiteExportV1, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def export_evidence_suite(
    suite_id: UUID,
    include_archived_items: bool = False,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    DatasetService.ensure_member(db, tenant_id, account_id)

    suite = (
        db.query(EvidenceSuite)
        .filter(EvidenceSuite.id == suite_id, EvidenceSuite.tenant_id == tenant_id)
        .first()
    )
    if not suite:
        raise HTTPException(status_code=404, detail=_DETAIL_SUITE_NOT_FOUND)

    ds = DatasetService.get_dataset(db, tenant_id, suite.dataset_id)
    DatasetService.assert_dataset_readable(db, ds, account_id)

    q = (
        db.query(EvidenceItem)
        .filter(EvidenceItem.tenant_id == tenant_id, EvidenceItem.suite_id == suite_id)
        .order_by(EvidenceItem.created_at.asc())
    )
    if not include_archived_items:
        q = q.filter(EvidenceItem.status != "archived")
    items = q.all()

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
                "tags": list(getattr(it, "tags", []) or []),
                "source_metadata": dict(getattr(it, "source_metadata", {}) or {}),
                "reference_sources": it.reference_sources,
                "retrieval_snapshot": it.retrieval_snapshot or {},
                "rag_config_snapshot": it.rag_config_snapshot or {},
                "notes": it.notes,
                "regression_case_id": str(it.regression_case_id) if it.regression_case_id else None,
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
        exported_at=_now_utc().isoformat(),
        dataset_id=suite.dataset_id,
        suite=suite_payload,
        items=items_payload,
    )


@router.get("/training-export", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def export_training_dataset(
    dataset_id: Annotated[UUID, Query(..., description="Dataset id to export")],
    format: Annotated[str, Query(description='jsonl or csv')] = "jsonl",
    include_feedback: Annotated[bool, Query()] = True,
    include_evidence: Annotated[bool, Query()] = True,
    include_archived_evidence: Annotated[bool, Query()] = False,
    max_rows_per_source: Annotated[int, Query(ge=1, le=10000)] = 2000,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Export a dataset-scoped training dataset assembled from feedback + evidence.

    Output format:
    - `jsonl`: one stable row per feedback/evidence record
    - `csv`: flattened export with nested JSON columns
    """
    DatasetService.ensure_member(db, tenant_id, account_id)
    ds = DatasetService.get_dataset(db, tenant_id, dataset_id)
    DatasetService.assert_dataset_readable(db, ds, account_id)

    fmt = str(format or "jsonl").strip().lower() or "jsonl"
    if fmt not in {"jsonl", "csv"}:
        raise HTTPException(status_code=400, detail="format must be one of: jsonl, csv")
    if not include_feedback and not include_evidence:
        raise HTTPException(status_code=400, detail="at least one of include_feedback/include_evidence must be true")

    rows: list[dict[str, Any]] = []
    if include_feedback:
        rows.extend(
            _collect_feedback_training_export_rows(
                db,
                tenant_id=tenant_id,
                dataset_id=dataset_id,
                limit=max_rows_per_source,
            )
        )
    if include_evidence:
        rows.extend(
            _collect_evidence_training_export_rows(
                db,
                tenant_id=tenant_id,
                dataset_id=dataset_id,
                include_archived=bool(include_archived_evidence),
                limit=max_rows_per_source,
            )
        )

    rows.sort(
        key=lambda row: (
            str(row.get("created_at") or ""),
            str(row.get("source_type") or ""),
            str(row.get("source_id") or ""),
        )
    )

    if fmt == "csv":
        content = _render_training_export_csv(rows)
        filename = f"dataset_{dataset_id}.training_export.csv"
        media_type = "text/csv"
    else:
        content = "\n".join(json.dumps(row, ensure_ascii=False, separators=(",", ":"), default=str) for row in rows)
        if content:
            content += "\n"
        filename = f"dataset_{dataset_id}.training_export.jsonl"
        media_type = "application/x-ndjson"

    return Response(
        content=content,
        media_type=media_type,
        headers=download_response_headers(filename),
    )


@router.get("/suites/{suite_id}/export-ltr-training", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def export_evidence_suite_ltr_training_bundle(
    suite_id: UUID,
    include_archived_items: bool = False,
    max_items: Annotated[int, Query(ge=1, le=10000, description='Max items to include in export')] = 2000,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Export a PII-minimized LTR training bundle from an Evidence Suite.

    Contents:
    - manifest.json: export metadata + feature spec
    - training_rows.ndjson: per-citation features + labels (0/1), grouped by query_hash
    - hard_negatives.ndjson: mined near-miss negatives (PII-safe) per query_hash

    Notes:
    - This endpoint intentionally avoids including raw query text in training rows.
    - It relies on per-item retrieval_snapshot for reproducibility; items without a snapshot are skipped.
    """
    from app.core.config import settings
    from app.rag.core.hashing import stable_hash
    from app.rag.evaluation.hard_negative_mining import mine_hard_negatives_for_case_from_trace
    from app.rag.reranker.ltr import LTRFeatureSpec, extract_ltr_features
    from app.rag.reranker.types import RerankCandidate

    DatasetService.ensure_member(db, tenant_id, account_id)

    suite = (
        db.query(EvidenceSuite)
        .filter(EvidenceSuite.id == suite_id, EvidenceSuite.tenant_id == tenant_id)
        .first()
    )
    if not suite:
        raise HTTPException(status_code=404, detail=_DETAIL_SUITE_NOT_FOUND)

    ds = DatasetService.get_dataset(db, tenant_id, suite.dataset_id)
    DatasetService.assert_dataset_readable(db, ds, account_id)

    q = (
        db.query(EvidenceItem)
        .filter(EvidenceItem.tenant_id == tenant_id, EvidenceItem.suite_id == suite_id)
        .order_by(EvidenceItem.created_at.asc())
        .limit(int(max_items or 0))
    )
    if not include_archived_items:
        q = q.filter(EvidenceItem.status != "archived")
    items = q.all()

    exported_at = _now_utc()

    spec_version = int(getattr(settings, "LTR_FEATURE_SPEC_VERSION", 1) or 1)
    spec = LTRFeatureSpec.from_version(spec_version)

    def _as_float(v: Any) -> float:
        try:
            if v is None:
                return 0.0
            return float(v)
        except Exception:
            return 0.0

    def _extract_reference_chunk_ids(item: EvidenceItem) -> set[str]:
        refs = getattr(item, "reference_sources", None) or []
        if not isinstance(refs, list):
            return set()
        out: set[str] = set()
        for src in refs:
            if not isinstance(src, dict):
                continue
            cid = str(src.get("chunk_id") or "").strip()
            if cid:
                out.add(cid)
        return out

    training_lines: list[str] = []
    hard_lines: list[str] = []

    items_total = int(len(items))
    items_with_snapshot = 0
    rows_total = 0
    hard_total = 0

    for it in items:
        snap = getattr(it, "retrieval_snapshot", None) or {}
        if not isinstance(snap, dict):
            continue
        citations = snap.get("citations") or []
        if not isinstance(citations, list) or not citations:
            continue

        items_with_snapshot += 1

        query = str(getattr(it, "query", "") or "")
        query_hash = stable_hash(query, length=64)
        ref_chunk_ids = _extract_reference_chunk_ids(it)

        metrics = snap.get("metrics") if isinstance(snap.get("metrics"), dict) else {}
        retrieval_cfg_hash = str(metrics.get("retrieval_config_hash") or "").strip() or None
        if retrieval_cfg_hash is None:
            # Best-effort: try to recover from retrieval_trace.
            trace = snap.get("retrieval_trace") if isinstance(snap.get("retrieval_trace"), dict) else None
            fp = (trace or {}).get("retrieval_config") if isinstance((trace or {}).get("retrieval_config"), dict) else None
            maybe = (fp or {}).get("hash") if isinstance(fp, dict) else None
            retrieval_cfg_hash = str(maybe or "").strip() or None

        # Training rows: per-citation features + labels.
        for rank, c in enumerate(citations, 1):
            if not isinstance(c, dict):
                continue
            cid = str(c.get("chunk_id") or "").strip()
            if not cid:
                continue

            meta = {
                "vector_score": _as_float(c.get("vector_score")),
                "bm25_score": _as_float(c.get("bm25_score")),
                "lexical_score": _as_float(c.get("lexical_score")),
                "sparse_score": _as_float(c.get("sparse_score")),
                # Prefer evidence API's overall score (relevance_score).
                "score": _as_float(c.get("relevance_score") or c.get("retrieval_score") or c.get("score")),
                "retrieval_role": c.get("retrieval_role"),
                # Optional KG ranking signals (low-cardinality, numeric only).
                "kg_pagerank": _as_float(c.get("kg_pagerank")),
                "kg_shared_events": _as_float(c.get("kg_shared_events")),
                "kg_path_length": _as_float(c.get("kg_path_length")),
                "kg_edge_conf_low": _as_float(c.get("kg_edge_conf_low")),
                "kg_edge_conf_mid": _as_float(c.get("kg_edge_conf_mid")),
                "kg_edge_conf_high": _as_float(c.get("kg_edge_conf_high")),
                "kg_evidence_anchored": _as_float(c.get("kg_evidence_anchored")),
            }
            values = extract_ltr_features(
                spec=spec,
                query="",  # reserved for future query-dependent features; keep export PII-minimized
                candidate=RerankCandidate(id=cid, text="", metadata=meta),
            )
            features = {name: float(v) for name, v in zip(spec.feature_names, values, strict=False)}

            row = {
                "schema": "mimirq.ltr_training_row.v1",
                "suite_id": str(suite.id),
                "item_id": str(it.id),
                "dataset_id": str(suite.dataset_id),
                "query_hash": query_hash,
                "retrieval_config_hash": retrieval_cfg_hash,
                "rank": int(rank),
                "label": int(1 if cid in ref_chunk_ids else 0),
                "candidate": {
                    "chunk_id": cid,
                    "document_id": str(c.get("document_id") or "").strip() or None,
                },
                "slices": {
                    "status": str(getattr(it, "status", "") or "").strip().lower() or None,
                    "tags": list(getattr(it, "tags", []) or []),
                },
                "features": features,
            }
            training_lines.append(json.dumps(row, ensure_ascii=False, separators=(",", ":"), default=str))
            rows_total += 1

        # Hard negatives: near-miss negatives before first positive (PII-safe).
        try:
            trace_record = {
                "citations": citations,
                "retrieval": {"retrieval_config_hash": retrieval_cfg_hash},
            }
            case = {"reference_sources": getattr(it, "reference_sources", None) or []}
            hn = mine_hard_negatives_for_case_from_trace(
                case=case,
                trace_record=trace_record,
                query_hash=query_hash,
                max_hard_negatives=10,
                max_negatives_per_document=2,
            )
            if isinstance(hn, dict):
                hn["suite_id"] = str(suite.id)
                hn["item_id"] = str(it.id)
                hn["dataset_id"] = str(suite.dataset_id)
                hn["tags"] = list(getattr(it, "tags", []) or [])
                hard_lines.append(json.dumps(hn, ensure_ascii=False, separators=(",", ":"), default=str))
                hard_total += 1
        except Exception as exc:
            # Hard negatives are best-effort; training rows are the primary export.
            logger.debug("Failed to export hard negative row; continuing training export: %s", exc)

    manifest: dict[str, Any] = {
        "schema": "mimirq.ltr_training_export.v1",
        "exported_at": exported_at.isoformat(),
        "tenant_id": str(tenant_id),
        "dataset_id": str(suite.dataset_id),
        "suite": {
            "id": str(suite.id),
            "name": str(getattr(suite, "name", "") or ""),
            "tags": list(getattr(suite, "tags", []) or []),
            "include_archived_items": bool(include_archived_items),
            "max_items": int(max_items or 0),
        },
        "feature_spec": {
            "version": int(spec_version),
            "schema": str(spec.schema),
            "feature_names": list(spec.feature_names),
        },
        "counts": {
            "items_total": int(items_total),
            "items_with_snapshot": int(items_with_snapshot),
            "training_rows": int(rows_total),
            "hard_negative_records": int(hard_total),
        },
    }

    # Best-effort audit log (PII-minimal).
    try:
        audit_log_event(
            db,
            tenant_id=tenant_id,
            actor_id=account_id,
            action="evidence_suite.export_ltr_training",
            resource_type="evidence_suite",
            resource_id=str(suite_id),
            details={
                "dataset_id": str(suite.dataset_id),
                "items_total": int(items_total),
                "items_with_snapshot": int(items_with_snapshot),
                "training_rows": int(rows_total),
                "hard_negative_records": int(hard_total),
                "feature_spec_version": int(spec_version),
            },
        )
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception as exc:
            logger.debug("Ignoring non-critical evidence router fallback failure: %s", exc)

    # Write ZIP bundle in memory (bounded by max_items).
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, separators=(",", ":"), default=str))
        zf.writestr(
            "training_rows.ndjson",
            ("\n".join(training_lines) + ("\n" if training_lines else "")).encode("utf-8"),
        )
        zf.writestr(
            "hard_negatives.ndjson",
            ("\n".join(hard_lines) + ("\n" if hard_lines else "")).encode("utf-8"),
        )
        zf.writestr(
            "README.txt",
            (
                "MimirQ Evidence Suite LTR Training Export\n\n"
                "- manifest.json: export metadata + LTR feature spec\n"
                "- training_rows.ndjson: one row per (query_hash, candidate chunk_id) with features + label\n"
                "- hard_negatives.ndjson: mined near-miss negatives (PII-safe) per query_hash\n"
                "\n"
                "Notes:\n"
                "- training_rows is PII-minimized: it does not include raw query text.\n"
                "- This export relies on per-item retrieval_snapshot for reproducibility.\n"
            ),
        )

    raw = buf.getvalue()
    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(getattr(suite, "name", "") or "evidence_suite"))[:64]
    filename = f"{safe}.ltr_training.zip"
    return Response(
        content=raw,
        media_type="application/zip",
        headers=download_response_headers(filename),
    )
