"""
Dataset precheck scan API.

Precheck scans are intended for "before ingestion" analysis on a local folder.
They are run-based (async), store progress in DB, and store per-file records on disk.
"""

import asyncio
import json
import re
import time
from datetime import UTC, datetime
from functools import partial
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Query as ORMQuery
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_account_id, get_tenant_id
from app.api.schemas.datasets import (
    DatasetPrecheckDiffResponse,
    DatasetPrecheckFindingListResponse,
    DatasetPrecheckIngestionSuggestionResponse,
    DatasetPrecheckNearDupResponse,
    DatasetPrecheckSampleReviewOut,
    DatasetPrecheckSampleReviewPatchRequest,
    DatasetPrecheckSamplesResponse,
    DatasetPrecheckScanRunCreateRequest,
    DatasetPrecheckScanRunListResponse,
    DatasetPrecheckScanRunOut,
    DatasetPrecheckSummary,
)
from app.api.schemas.sources import IngestionPolicyImportResponse
from app.api.utils import DEFAULT_HTTP_EXCEPTION_RESPONSES, file_response_headers
from app.core.async_bridge import run_blocking_in_thread
from app.core.config import settings
from app.core.database import SessionLocal, get_db
from app.models.dataset_precheck_scan import DatasetPrecheckScanRun as DBDatasetPrecheckScanRun
from app.rag.core.logging import get_logger
from app.services.dataset_precheck_diff import diff_precheck_summaries
from app.services.dataset_precheck_ingestion_suggestion import (
    apply_ingestion_policy_suggestion,
    build_ingestion_policy_suggestion,
)
from app.services.dataset_precheck_scan_runner import run_dataset_precheck_scan
from app.services.dataset_precheck_service import (
    _scan_run_out_from_row,
    apply_precheck_sample_reviews,
    get_dataset_for_precheck,
    list_precheck_files_by_dir_prefix,
    list_precheck_finding_files,
    load_precheck_near_dups_from_row,
    load_precheck_sample_reviews_from_row,
    load_precheck_samples_from_row,
    load_precheck_summary_from_row,
    upsert_precheck_sample_review_for_row,
)
from app.services.dataset_scan_session import (
    DatasetScanSession,
    ScanTransaction,
    expire_stale_scan_runs,
    fail_unhanded_scan_run,
    persist_scan_handoff_update,
    settle_scan_enqueue,
    submit_local_scan_run,
)
from app.services.ingestion_policy import parse_ingestion_policy_from_metadata
from app.services.managed_handoff import prepare_managed_handoff
from app.services.report_html import render_precheck_html
from app.tasks.queue import (
    enqueue_dataset_precheck_scan,
    get_task_job_status,
    register_local_scan_run_active,
    unregister_local_scan_run_active,
)

logger = get_logger(__name__)
router = APIRouter(responses=DEFAULT_HTTP_EXCEPTION_RESPONSES)
_SCAN_RUN_NOT_FOUND_DETAIL = "Scan run not found"


def _precheck_scan_run_query(
    db: Session, *, tenant_id: UUID, dataset_id: UUID, scan_run_id: UUID
) -> ORMQuery[DBDatasetPrecheckScanRun]:
    return db.query(DBDatasetPrecheckScanRun).filter(
        DBDatasetPrecheckScanRun.id == scan_run_id,
        DBDatasetPrecheckScanRun.tenant_id == tenant_id,
        DBDatasetPrecheckScanRun.dataset_id == dataset_id,
    )


def _require_precheck_scan_run(
    db: Session,
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    scan_run_id: UUID,
    not_found_detail: str = _SCAN_RUN_NOT_FOUND_DETAIL,
) -> DBDatasetPrecheckScanRun:
    row = _precheck_scan_run_query(db, tenant_id=tenant_id, dataset_id=dataset_id, scan_run_id=scan_run_id).first()
    if row is None:
        raise HTTPException(status_code=404, detail=not_found_detail)
    return row


def _precheck_scan_event_snapshot(*, tenant_id: UUID, dataset_id: UUID, scan_run_id: UUID) -> tuple[str, str] | None:
    """Build a JSON-ready event while the polling worker owns its session."""
    with SessionLocal() as db:
        row = _precheck_scan_run_query(db, tenant_id=tenant_id, dataset_id=dataset_id, scan_run_id=scan_run_id).first()
        if row is None:
            return None
        snapshot = DatasetPrecheckScanRunOut.model_validate(_scan_run_out_from_row(row))
        return (
            json.dumps(snapshot.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":")),
            snapshot.status.lower(),
        )


async def _expire_stale_precheck_scan_runs(transaction: ScanTransaction, *, tenant_id: UUID, dataset_id: UUID) -> int:
    return await expire_stale_scan_runs(
        transaction,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        now=datetime.now(UTC),
        kind="precheck",
        queue_enabled=settings.TASK_QUEUE_ENABLED,
        get_job_status=get_task_job_status,
    )


def _run_precheck_scan_background(*, tenant_id: UUID, dataset_id: UUID, scan_run_id: UUID) -> None:
    """
    Local executor worker when the queue is disabled.

    Uses a dedicated DB session and marks the run as failed on exception.
    """
    with SessionLocal() as db:
        register_local_scan_run_active(
            kind="precheck", tenant_id=tenant_id, dataset_id=dataset_id, scan_run_id=scan_run_id
        )
        try:
            run_dataset_precheck_scan(db, tenant_id=tenant_id, dataset_id=dataset_id, scan_run_id=scan_run_id)
        except Exception as exc:
            logger.exception("Dataset precheck scan failed: scan_run_id=%s", scan_run_id)
            db.rollback()
            try:
                row = _precheck_scan_run_query(
                    db, tenant_id=tenant_id, dataset_id=dataset_id, scan_run_id=scan_run_id
                ).first()
                if row is not None:
                    row.status = "failed"
                    row.error_message = str(exc)[:200]
                    db.commit()
            except Exception:
                db.rollback()
                logger.warning(
                    "Failed to persist precheck background failure state: scan_run_id=%s", scan_run_id, exc_info=True
                )
        finally:
            unregister_local_scan_run_active(
                kind="precheck", tenant_id=tenant_id, dataset_id=dataset_id, scan_run_id=scan_run_id
            )


async def _prepare_precheck_scan_run(
    transaction: ScanTransaction,
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    account_id: str,
    body: DatasetPrecheckScanRunCreateRequest,
) -> tuple[UUID, DatasetPrecheckScanRunOut]:

    def authorize(db: Session) -> None:
        get_dataset_for_precheck(
            db, tenant_id=tenant_id, dataset_id=dataset_id, account_id=account_id, require_write=True
        )

    await transaction.run(authorize)
    expired = await _expire_stale_precheck_scan_runs(transaction, tenant_id=tenant_id, dataset_id=dataset_id)
    if expired:
        await transaction.run(lambda db: db.commit())

    def has_active_run(db: Session) -> bool:
        return (
            db.query(DBDatasetPrecheckScanRun)
            .filter(
                DBDatasetPrecheckScanRun.tenant_id == tenant_id,
                DBDatasetPrecheckScanRun.dataset_id == dataset_id,
                DBDatasetPrecheckScanRun.status.in_(["pending", "running"]),
            )
            .order_by(DBDatasetPrecheckScanRun.created_at.desc())
            .first()
            is not None
        )

    if await transaction.run(has_active_run):
        raise HTTPException(status_code=409, detail="A precheck scan run is already pending/running for this dataset")

    await transaction.run(lambda db: db.rollback())
    transaction.raise_if_cancelled()

    def insert_run(db: Session) -> tuple[UUID, DatasetPrecheckScanRunOut]:
        row = DBDatasetPrecheckScanRun(
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            requested_by=account_id,
            kind="path",
            status="pending",
            progress=0,
            config=body.model_dump(mode="json", exclude_none=True),
            summary={},
            artifacts={},
        )
        db.add(row)
        db.commit()
        db.refresh(row)
        return (row.id, DatasetPrecheckScanRunOut(**_scan_run_out_from_row(row)))

    try:
        return await prepare_managed_handoff(
            insert_run,
            recover_cancelled=lambda worker_db, prepared: fail_unhanded_scan_run(
                worker_db,
                kind="precheck",
                tenant_id=tenant_id,
                dataset_id=dataset_id,
                scan_run_id=prepared[0],
                error_message="scan_request_cancelled_before_handoff",
            ),
        )
    except IntegrityError as exc:
        await transaction.run(lambda db: db.rollback())
        expired_after_conflict = await _expire_stale_precheck_scan_runs(
            transaction, tenant_id=tenant_id, dataset_id=dataset_id
        )
        if expired_after_conflict:
            await transaction.run(lambda db: db.commit())
        if await transaction.run(has_active_run):
            raise HTTPException(
                status_code=409, detail="A precheck scan run is already pending/running for this dataset"
            ) from exc
        raise


@router.post("/{dataset_id}/precheck/scan-runs", response_model=DatasetPrecheckScanRunOut, status_code=201)
async def create_dataset_precheck_scan_run(
    dataset_id: UUID,
    body: DatasetPrecheckScanRunCreateRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
):
    async with DatasetScanSession(SessionLocal) as transaction:
        scan_run_id, result = await _prepare_precheck_scan_run(
            transaction, tenant_id=tenant_id, dataset_id=dataset_id, account_id=account_id, body=body
        )
        job_id = f"dataset_precheck_scan:{tenant_id}:{dataset_id}:{scan_run_id}"
        enqueue_task = asyncio.create_task(
            enqueue_dataset_precheck_scan(
                tenant_id=tenant_id,
                dataset_id=dataset_id,
                scan_run_id=scan_run_id,
                requested_by=account_id,
                job_id=job_id,
            )
        )
        try:
            task_id = await settle_scan_enqueue(
                enqueue_task,
                kind="precheck",
                tenant_id=tenant_id,
                dataset_id=dataset_id,
                scan_run_id=scan_run_id,
            )
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Failed to enqueue dataset precheck scan job") from exc
        if task_id is None:
            try:
                submit_local_scan_run(
                    partial(
                        _run_precheck_scan_background,
                        tenant_id=tenant_id,
                        dataset_id=dataset_id,
                        scan_run_id=scan_run_id,
                    ),
                    kind="precheck",
                    tenant_id=tenant_id,
                    dataset_id=dataset_id,
                    scan_run_id=scan_run_id,
                )
            except Exception as exc:
                try:
                    await persist_scan_handoff_update(
                        partial(
                            fail_unhanded_scan_run,
                            kind="precheck",
                            tenant_id=tenant_id,
                            dataset_id=dataset_id,
                            scan_run_id=scan_run_id,
                            error_message=f"local_scan_submit_failed: {str(exc)[:160]}",
                        )
                    )
                except Exception:
                    logger.warning(
                        "Failed to record local scan submission failure: scan_run_id=%s", scan_run_id, exc_info=True
                    )
                raise HTTPException(status_code=503, detail="Failed to enqueue dataset precheck scan job") from exc
        return result


@router.get("/{dataset_id}/precheck/scan-runs", response_model=DatasetPrecheckScanRunListResponse)
def list_dataset_precheck_scan_runs(
    dataset_id: UUID,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    get_dataset_for_precheck(db, tenant_id=tenant_id, dataset_id=dataset_id, account_id=account_id, require_write=False)
    q = db.query(DBDatasetPrecheckScanRun).filter(
        DBDatasetPrecheckScanRun.tenant_id == tenant_id, DBDatasetPrecheckScanRun.dataset_id == dataset_id
    )
    total = q.count()
    rows = q.order_by(DBDatasetPrecheckScanRun.created_at.desc()).offset(skip).limit(limit).all()
    return DatasetPrecheckScanRunListResponse(
        total=total, items=[DatasetPrecheckScanRunOut(**_scan_run_out_from_row(r)) for r in rows]
    )


@router.get("/{dataset_id}/precheck/scan-runs/{scan_run_id}", response_model=DatasetPrecheckScanRunOut)
def get_dataset_precheck_scan_run(
    dataset_id: UUID,
    scan_run_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    get_dataset_for_precheck(db, tenant_id=tenant_id, dataset_id=dataset_id, account_id=account_id, require_write=False)
    row = _require_precheck_scan_run(db, tenant_id=tenant_id, dataset_id=dataset_id, scan_run_id=scan_run_id)
    return DatasetPrecheckScanRunOut(**_scan_run_out_from_row(row))


@router.get("/{dataset_id}/precheck/scan-runs/{scan_run_id}/summary", response_model=DatasetPrecheckSummary)
def get_dataset_precheck_summary(
    dataset_id: UUID,
    scan_run_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    get_dataset_for_precheck(db, tenant_id=tenant_id, dataset_id=dataset_id, account_id=account_id, require_write=False)
    row = _require_precheck_scan_run(db, tenant_id=tenant_id, dataset_id=dataset_id, scan_run_id=scan_run_id)
    return load_precheck_summary_from_row(row)


@router.get(
    "/{dataset_id}/precheck/scan-runs/{scan_run_id}/findings/{finding_key}",
    response_model=DatasetPrecheckFindingListResponse,
)
def list_dataset_precheck_finding_files(
    dataset_id: UUID,
    scan_run_id: UUID,
    finding_key: str,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    return list_precheck_finding_files(
        db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        account_id=account_id,
        scan_run_id=scan_run_id,
        finding_key=finding_key,
        skip=skip,
        limit=limit,
    )


@router.get("/{dataset_id}/precheck/scan-runs/{scan_run_id}/files", response_model=DatasetPrecheckFindingListResponse)
def list_dataset_precheck_files(
    dataset_id: UUID,
    scan_run_id: UUID,
    dir_prefix: Annotated[
        str | None, Query(max_length=1024, description="Optional: directory prefix under scan root")
    ] = None,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    return list_precheck_files_by_dir_prefix(
        db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        account_id=account_id,
        scan_run_id=scan_run_id,
        dir_prefix=dir_prefix,
        skip=skip,
        limit=limit,
    )


@router.post("/{dataset_id}/precheck/scan-runs/{scan_run_id}/cancel", response_model=DatasetPrecheckScanRunOut)
def cancel_dataset_precheck_scan_run(
    dataset_id: UUID,
    scan_run_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    get_dataset_for_precheck(db, tenant_id=tenant_id, dataset_id=dataset_id, account_id=account_id, require_write=True)
    row = _require_precheck_scan_run(db, tenant_id=tenant_id, dataset_id=dataset_id, scan_run_id=scan_run_id)
    st = row.status.lower()
    if st in {"completed", "failed", "cancelled"}:
        return DatasetPrecheckScanRunOut(**_scan_run_out_from_row(row))
    row.status = "cancelled"
    db.commit()
    db.refresh(row)
    return DatasetPrecheckScanRunOut(**_scan_run_out_from_row(row))


@router.get("/{dataset_id}/precheck/scan-runs/{scan_run_id}/events")
def stream_dataset_precheck_scan_events(
    dataset_id: UUID,
    scan_run_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db, scope="function")],
):
    """
    Server-sent events (SSE) stream for scan run progress.

    This allows web UIs to avoid polling while a scan is running.
    """
    get_dataset_for_precheck(db, tenant_id=tenant_id, dataset_id=dataset_id, account_id=account_id, require_write=False)

    async def gen():
        last_payload: str | None = None
        last_keepalive = time.monotonic()
        yield ": keepalive\n\n"
        while True:
            event = await run_blocking_in_thread(
                _precheck_scan_event_snapshot, tenant_id=tenant_id, dataset_id=dataset_id, scan_run_id=scan_run_id
            )
            if event is None:
                break
            payload, st = event
            if payload != last_payload:
                last_payload = payload
                yield f"data: {payload}\n\n"
                last_keepalive = time.monotonic()
            elif time.monotonic() - last_keepalive > 15.0:
                yield ": keepalive\n\n"
                last_keepalive = time.monotonic()
            if st not in {"pending", "running"}:
                break
            await asyncio.sleep(1.0)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )


@router.get("/{dataset_id}/precheck/scan-runs/{scan_run_id}/samples", response_model=DatasetPrecheckSamplesResponse)
def get_dataset_precheck_samples(
    dataset_id: UUID,
    scan_run_id: UUID,
    size: Annotated[int, Query(ge=0, le=2000)] = 60,
    prefer_artifact: Annotated[bool, Query()] = True,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    get_dataset_for_precheck(db, tenant_id=tenant_id, dataset_id=dataset_id, account_id=account_id, require_write=False)
    row = _require_precheck_scan_run(db, tenant_id=tenant_id, dataset_id=dataset_id, scan_run_id=scan_run_id)
    raw = load_precheck_samples_from_row(row, tenant_id=tenant_id, size=size, prefer_artifact=prefer_artifact)
    raw = apply_precheck_sample_reviews(raw, load_precheck_sample_reviews_from_row(row, tenant_id=tenant_id))
    return DatasetPrecheckSamplesResponse.model_validate(raw)


@router.patch(
    "/{dataset_id}/precheck/scan-runs/{scan_run_id}/samples/review", response_model=DatasetPrecheckSampleReviewOut
)
def patch_dataset_precheck_sample_review(
    dataset_id: UUID,
    scan_run_id: UUID,
    body: DatasetPrecheckSampleReviewPatchRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    get_dataset_for_precheck(db, tenant_id=tenant_id, dataset_id=dataset_id, account_id=account_id, require_write=True)
    row = _require_precheck_scan_run(db, tenant_id=tenant_id, dataset_id=dataset_id, scan_run_id=scan_run_id)
    samples = DatasetPrecheckSamplesResponse.model_validate(
        load_precheck_samples_from_row(row, tenant_id=tenant_id, size=2000, prefer_artifact=True)
    )
    sample_groups = (
        samples.representative,
        samples.top_large_files,
        samples.top_long_text,
        *samples.needs_review.values(),
    )
    sample_names = {sample.name.strip() for group in sample_groups for sample in group}
    if body.file_name not in sample_names:
        raise HTTPException(status_code=404, detail="Sample file not found in this precheck run")
    review = upsert_precheck_sample_review_for_row(
        row, tenant_id=tenant_id, account_id=account_id, file_name=body.file_name, disposition=body.disposition
    )
    db.commit()
    db.refresh(row)
    return DatasetPrecheckSampleReviewOut(
        file_name=body.file_name,
        review_disposition=review["review_disposition"],
        reviewed_at=review["reviewed_at"],
        reviewed_by=review["reviewed_by"],
    )


@router.get("/{dataset_id}/precheck/scan-runs/{scan_run_id}/near-dups", response_model=DatasetPrecheckNearDupResponse)
def get_dataset_precheck_near_dups(
    dataset_id: UUID,
    scan_run_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    get_dataset_for_precheck(db, tenant_id=tenant_id, dataset_id=dataset_id, account_id=account_id, require_write=False)
    row = _require_precheck_scan_run(db, tenant_id=tenant_id, dataset_id=dataset_id, scan_run_id=scan_run_id)
    raw = load_precheck_near_dups_from_row(row, tenant_id=tenant_id)
    return DatasetPrecheckNearDupResponse.model_validate(raw)


@router.get("/{dataset_id}/precheck/scan-runs/{scan_run_id}/diff", response_model=DatasetPrecheckDiffResponse)
def diff_dataset_precheck_scan_runs(
    dataset_id: UUID,
    scan_run_id: UUID,
    base_scan_run_id: Annotated[UUID, Query(..., description="Base scan run id to compare against")],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    get_dataset_for_precheck(db, tenant_id=tenant_id, dataset_id=dataset_id, account_id=account_id, require_write=False)
    base = _require_precheck_scan_run(
        db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        scan_run_id=base_scan_run_id,
        not_found_detail="Base scan run not found",
    )
    target = _require_precheck_scan_run(
        db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        scan_run_id=scan_run_id,
        not_found_detail="Target scan run not found",
    )
    base_summary = base.summary
    base_summary = base_summary if isinstance(base_summary, dict) else {}
    target_summary = target.summary
    target_summary = target_summary if isinstance(target_summary, dict) else {}
    if not base_summary or not target_summary:
        raise HTTPException(status_code=404, detail="Summary not available")
    diff = diff_precheck_summaries(
        base_scan_run_id=base_scan_run_id,
        target_scan_run_id=scan_run_id,
        base_summary=base_summary,
        target_summary=target_summary,
    )
    return DatasetPrecheckDiffResponse(**diff)


@router.get(
    "/{dataset_id}/precheck/scan-runs/{scan_run_id}/suggest-ingestion-policy",
    response_model=DatasetPrecheckIngestionSuggestionResponse,
)
def get_dataset_precheck_ingestion_policy_suggestion(
    dataset_id: UUID,
    scan_run_id: UUID,
    max_names_per_bucket: Annotated[int, Query(ge=0, le=2000)] = 50,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    dataset = get_dataset_for_precheck(
        db, tenant_id=tenant_id, dataset_id=dataset_id, account_id=account_id, require_write=False
    )
    before_policy = parse_ingestion_policy_from_metadata(dict(dataset.dataset_metadata or {}))
    row = _require_precheck_scan_run(db, tenant_id=tenant_id, dataset_id=dataset_id, scan_run_id=scan_run_id)
    suggestion = build_ingestion_policy_suggestion(
        row, tenant_id=tenant_id, before_policy=before_policy, max_names_per_bucket=max_names_per_bucket
    )
    return DatasetPrecheckIngestionSuggestionResponse(**suggestion)


@router.post(
    "/{dataset_id}/precheck/scan-runs/{scan_run_id}/apply-ingestion-policy",
    response_model=IngestionPolicyImportResponse,
)
def apply_dataset_precheck_ingestion_policy_suggestion(
    dataset_id: UUID,
    scan_run_id: UUID,
    replace: Annotated[bool, Query(description="Whether to overwrite existing dataset ingestion_policy")] = False,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    dataset = get_dataset_for_precheck(
        db, tenant_id=tenant_id, dataset_id=dataset_id, account_id=account_id, require_write=True
    )
    row = _require_precheck_scan_run(db, tenant_id=tenant_id, dataset_id=dataset_id, scan_run_id=scan_run_id)
    res = apply_ingestion_policy_suggestion(db, dataset=dataset, scan_run=row, tenant_id=tenant_id, replace=replace)
    return IngestionPolicyImportResponse(**res)


@router.get("/{dataset_id}/precheck/scan-runs/{scan_run_id}/export")
def export_dataset_precheck_summary_json(
    dataset_id: UUID,
    scan_run_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    get_dataset_for_precheck(db, tenant_id=tenant_id, dataset_id=dataset_id, account_id=account_id, require_write=False)
    row = _require_precheck_scan_run(db, tenant_id=tenant_id, dataset_id=dataset_id, scan_run_id=scan_run_id)
    summary = load_precheck_summary_from_row(row)
    content = summary.model_dump_json()
    filename = f"dataset_{dataset_id}.precheck.json"
    return Response(content=content, media_type="application/json", headers=file_response_headers(filename))


@router.get("/{dataset_id}/precheck/scan-runs/{scan_run_id}/export-html")
def export_dataset_precheck_html_report(
    dataset_id: UUID,
    scan_run_id: UUID,
    redact: Annotated[bool, Query(description="Whether to redact dataset/path for sharing")] = True,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    dataset = get_dataset_for_precheck(
        db, tenant_id=tenant_id, dataset_id=dataset_id, account_id=account_id, require_write=False
    )
    row = _require_precheck_scan_run(db, tenant_id=tenant_id, dataset_id=dataset_id, scan_run_id=scan_run_id)
    cfg = row.config
    cfg = cfg if isinstance(cfg, dict) else {}
    artifacts = row.artifacts
    artifacts = artifacts if isinstance(artifacts, dict) else {}
    summary = load_precheck_summary_from_row(row)
    effective_redact = redact or bool(cfg.get("redact_paths", False))
    root_path = artifacts.get("root_path")
    samples = None
    # Rebuild file lists only when the original scan's path policy permits it.
    if not effective_redact or bool(cfg.get("redact_paths", False)):
        try:
            samples = load_precheck_samples_from_row(
                row, tenant_id=tenant_id, size=int(cfg.get("sample_size") or 0), prefer_artifact=True
            )
        except Exception as exc:
            logger.warning(
                "Precheck HTML sample loading failed: tenant_id=%s scan_run_id=%s error_type=%s",
                tenant_id,
                scan_run_id,
                type(exc).__name__,
            )
    html = render_precheck_html(
        title="MimirQ · 预检扫描报告",
        dataset_name=dataset.name,
        dataset_id=str(dataset_id),
        root_path=root_path,
        generated_at=summary.generated_at,
        summary=summary.model_dump(),
        samples=samples,
        redact=effective_redact,
    )
    safe = re.sub("[^a-zA-Z0-9_.-]+", "_", str(dataset.name or "dataset"))[:64]
    filename = f"{safe}.precheck.html"
    return Response(content=html, media_type="text/html; charset=utf-8", headers=file_response_headers(filename))
