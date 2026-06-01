"""
Dataset precheck scan API.

Precheck scans are intended for "before ingestion" analysis on a local folder.
They are run-based (async), store progress in DB, and store per-file records on disk.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.dataset_precheck import (
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
from app.api.schemas.ingestion_policy import IngestionPolicyImportResponse
from app.api.utils.response_headers import download_response_headers
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
from app.services.ingestion_policy import parse_ingestion_policy_from_metadata
from app.services.report_html import render_precheck_html
from app.tasks.queue import enqueue_dataset_precheck_scan

logger = get_logger(__name__)

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)

_SCAN_RUN_NOT_FOUND_DETAIL = "Scan run not found"


def _collect_precheck_sample_names(raw: dict[str, object]) -> set[str]:
    names: set[str] = set()

    def _pull(items: object) -> None:
        if not isinstance(items, list):
            return
        for item in items:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if name:
                names.add(name)

    _pull(raw.get("representative"))
    _pull(raw.get("top_large_files"))
    _pull(raw.get("top_long_text"))
    needs_review = raw.get("needs_review")
    if isinstance(needs_review, dict):
        for items in needs_review.values():
            _pull(items)
    return names


def _run_precheck_scan_background(
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    scan_run_id: UUID,
) -> None:
    """
    BackgroundTasks wrapper when the queue is disabled.

    Uses a dedicated DB session and marks the run as failed on exception.
    """
    db = SessionLocal()
    try:
        run_dataset_precheck_scan(db, tenant_id=tenant_id, dataset_id=dataset_id, scan_run_id=scan_run_id)
    except Exception as exc:  # noqa: BLE001
        try:
            row = (
                db.query(DBDatasetPrecheckScanRun)
                .filter(
                    DBDatasetPrecheckScanRun.id == scan_run_id,
                    DBDatasetPrecheckScanRun.tenant_id == tenant_id,
                    DBDatasetPrecheckScanRun.dataset_id == dataset_id,
                )
                .first()
            )
            if row is not None:
                row.status = "failed"
                row.error_message = str(exc)[:200]
                db.commit()
        except Exception as update_exc:
            logger.debug("Ignoring precheck background failure status update failure: %s", update_exc)
    finally:
        db.close()


@router.post("/{dataset_id}/precheck/scan-runs", response_model=DatasetPrecheckScanRunOut, status_code=201, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def create_dataset_precheck_scan_run(
    dataset_id: UUID,
    body: DatasetPrecheckScanRunCreateRequest,
    background_tasks: BackgroundTasks,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    # Starting a local scan is privileged (reads filesystem) -> require dataset write permission.
    get_dataset_for_precheck(db, tenant_id=tenant_id, dataset_id=dataset_id, account_id=account_id, require_write=True)

    existing = (
        db.query(DBDatasetPrecheckScanRun)
        .filter(
            DBDatasetPrecheckScanRun.tenant_id == tenant_id,
            DBDatasetPrecheckScanRun.dataset_id == dataset_id,
            DBDatasetPrecheckScanRun.status.in_(["pending", "running"]),
        )
        .order_by(DBDatasetPrecheckScanRun.created_at.desc())
        .first()
    )
    if existing is not None:
        raise HTTPException(status_code=409, detail="A precheck scan run is already pending/running for this dataset")

    cfg = body.model_dump(exclude_none=True)
    row = DBDatasetPrecheckScanRun(
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        requested_by=account_id,
        kind="path",
        status="pending",
        progress=0,
        config=cfg,
        summary={},
        artifacts={},
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    job_id = f"dataset_precheck_scan:{tenant_id}:{dataset_id}:{row.id}"
    task_id = await enqueue_dataset_precheck_scan(
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        scan_run_id=row.id,
        requested_by=account_id,
        job_id=job_id,
    )
    if not task_id:
        background_tasks.add_task(
            _run_precheck_scan_background,
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            scan_run_id=row.id,
        )

    return DatasetPrecheckScanRunOut(**_scan_run_out_from_row(row))


@router.get("/{dataset_id}/precheck/scan-runs", response_model=DatasetPrecheckScanRunListResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
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

    q = (
        db.query(DBDatasetPrecheckScanRun)
        .filter(DBDatasetPrecheckScanRun.tenant_id == tenant_id, DBDatasetPrecheckScanRun.dataset_id == dataset_id)
    )
    total = int(q.count())
    rows = (
        q.order_by(DBDatasetPrecheckScanRun.created_at.desc())
        .offset(int(skip or 0))
        .limit(int(limit or 20))
        .all()
    )
    return DatasetPrecheckScanRunListResponse(total=total, items=[DatasetPrecheckScanRunOut(**_scan_run_out_from_row(r)) for r in rows])


@router.get("/{dataset_id}/precheck/scan-runs/{scan_run_id}", response_model=DatasetPrecheckScanRunOut, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def get_dataset_precheck_scan_run(
    dataset_id: UUID,
    scan_run_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    get_dataset_for_precheck(db, tenant_id=tenant_id, dataset_id=dataset_id, account_id=account_id, require_write=False)

    row = (
        db.query(DBDatasetPrecheckScanRun)
        .filter(
            DBDatasetPrecheckScanRun.id == scan_run_id,
            DBDatasetPrecheckScanRun.tenant_id == tenant_id,
            DBDatasetPrecheckScanRun.dataset_id == dataset_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail=_SCAN_RUN_NOT_FOUND_DETAIL)
    return DatasetPrecheckScanRunOut(**_scan_run_out_from_row(row))


@router.get("/{dataset_id}/precheck/scan-runs/{scan_run_id}/summary", response_model=DatasetPrecheckSummary, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def get_dataset_precheck_summary(
    dataset_id: UUID,
    scan_run_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    get_dataset_for_precheck(db, tenant_id=tenant_id, dataset_id=dataset_id, account_id=account_id, require_write=False)
    row = (
        db.query(DBDatasetPrecheckScanRun)
        .filter(
            DBDatasetPrecheckScanRun.id == scan_run_id,
            DBDatasetPrecheckScanRun.tenant_id == tenant_id,
            DBDatasetPrecheckScanRun.dataset_id == dataset_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail=_SCAN_RUN_NOT_FOUND_DETAIL)
    return load_precheck_summary_from_row(row)


@router.get(
    "/{dataset_id}/precheck/scan-runs/{scan_run_id}/findings/{finding_key}",
    response_model=DatasetPrecheckFindingListResponse,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
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
        skip=int(skip or 0),
        limit=int(limit or 50),
    )


@router.get(
    "/{dataset_id}/precheck/scan-runs/{scan_run_id}/files",
    response_model=DatasetPrecheckFindingListResponse,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def list_dataset_precheck_files(
    dataset_id: UUID,
    scan_run_id: UUID,
    dir_prefix: Annotated[str | None, Query(max_length=1024, description='Optional: directory prefix under scan root')] = None,
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
        skip=int(skip or 0),
        limit=int(limit or 50),
    )


@router.post("/{dataset_id}/precheck/scan-runs/{scan_run_id}/cancel", response_model=DatasetPrecheckScanRunOut, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def cancel_dataset_precheck_scan_run(
    dataset_id: UUID,
    scan_run_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    # Cancelling affects the run state -> require dataset write permission.
    get_dataset_for_precheck(db, tenant_id=tenant_id, dataset_id=dataset_id, account_id=account_id, require_write=True)

    row = (
        db.query(DBDatasetPrecheckScanRun)
        .filter(
            DBDatasetPrecheckScanRun.id == scan_run_id,
            DBDatasetPrecheckScanRun.tenant_id == tenant_id,
            DBDatasetPrecheckScanRun.dataset_id == dataset_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail=_SCAN_RUN_NOT_FOUND_DETAIL)

    st = str(getattr(row, "status", "") or "").lower()
    if st in {"completed", "failed", "cancelled"}:
        return DatasetPrecheckScanRunOut(**_scan_run_out_from_row(row))

    row.status = "cancelled"
    db.commit()
    db.refresh(row)
    return DatasetPrecheckScanRunOut(**_scan_run_out_from_row(row))


@router.get("/{dataset_id}/precheck/scan-runs/{scan_run_id}/events", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def stream_dataset_precheck_scan_events(
    dataset_id: UUID,
    scan_run_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Server-sent events (SSE) stream for scan run progress.

    This allows web UIs to avoid polling while a scan is running.
    """
    # Read access is enough to observe progress.
    get_dataset_for_precheck(db, tenant_id=tenant_id, dataset_id=dataset_id, account_id=account_id, require_write=False)

    async def gen():  # noqa: ANN202
        last_payload: str | None = None
        last_keepalive = time.monotonic()
        # Send an immediate frame so clients/proxies don't see an idle connection.
        yield ": keepalive\n\n"
        while True:
            db2 = SessionLocal()
            try:
                row = (
                    db2.query(DBDatasetPrecheckScanRun)
                    .filter(
                        DBDatasetPrecheckScanRun.id == scan_run_id,
                        DBDatasetPrecheckScanRun.tenant_id == tenant_id,
                        DBDatasetPrecheckScanRun.dataset_id == dataset_id,
                    )
                    .first()
                )
                if row is None:
                    break
                out = _scan_run_out_from_row(row)
                payload = json.dumps(out, ensure_ascii=False, separators=(",", ":"))
                st = str(out.get("status") or "").lower()
            finally:
                db2.close()

            if payload != last_payload:
                last_payload = payload
                yield f"data: {payload}\n\n"
                last_keepalive = time.monotonic()
            elif (time.monotonic() - last_keepalive) > 15.0:
                # Keep the connection alive even if the payload doesn't change for a while.
                yield ": keepalive\n\n"
                last_keepalive = time.monotonic()

            if st not in {"pending", "running"}:
                break
            await asyncio.sleep(1.0)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get(
    "/{dataset_id}/precheck/scan-runs/{scan_run_id}/samples",
    response_model=DatasetPrecheckSamplesResponse,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
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
    row = (
        db.query(DBDatasetPrecheckScanRun)
        .filter(
            DBDatasetPrecheckScanRun.id == scan_run_id,
            DBDatasetPrecheckScanRun.tenant_id == tenant_id,
            DBDatasetPrecheckScanRun.dataset_id == dataset_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail=_SCAN_RUN_NOT_FOUND_DETAIL)

    raw = load_precheck_samples_from_row(row, tenant_id=tenant_id, size=int(size or 0), prefer_artifact=bool(prefer_artifact))
    raw = apply_precheck_sample_reviews(
        raw,
        load_precheck_sample_reviews_from_row(row, tenant_id=tenant_id),
    )
    try:
        return DatasetPrecheckSamplesResponse(**raw)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Invalid samples payload: {str(exc)[:200]}") from exc


@router.patch(
    "/{dataset_id}/precheck/scan-runs/{scan_run_id}/samples/review",
    response_model=DatasetPrecheckSampleReviewOut,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
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
    get_dataset_for_precheck(
        db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        account_id=account_id,
        require_write=True,
    )
    row = (
        db.query(DBDatasetPrecheckScanRun)
        .filter(
            DBDatasetPrecheckScanRun.id == scan_run_id,
            DBDatasetPrecheckScanRun.tenant_id == tenant_id,
            DBDatasetPrecheckScanRun.dataset_id == dataset_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail=_SCAN_RUN_NOT_FOUND_DETAIL)

    sample_names = _collect_precheck_sample_names(
        load_precheck_samples_from_row(
            row,
            tenant_id=tenant_id,
            size=2000,
            prefer_artifact=True,
        )
    )
    if body.file_name not in sample_names:
        raise HTTPException(status_code=404, detail="Sample file not found in this precheck run")

    review = upsert_precheck_sample_review_for_row(
        row,
        tenant_id=tenant_id,
        account_id=account_id,
        file_name=body.file_name,
        disposition=body.disposition,
    )
    db.commit()
    db.refresh(row)
    return DatasetPrecheckSampleReviewOut(
        file_name=body.file_name,
        review_disposition=str(review["review_disposition"]),
        reviewed_at=review["reviewed_at"],
        reviewed_by=review.get("reviewed_by"),
    )


@router.get(
    "/{dataset_id}/precheck/scan-runs/{scan_run_id}/near-dups",
    response_model=DatasetPrecheckNearDupResponse,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def get_dataset_precheck_near_dups(
    dataset_id: UUID,
    scan_run_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    get_dataset_for_precheck(db, tenant_id=tenant_id, dataset_id=dataset_id, account_id=account_id, require_write=False)
    row = (
        db.query(DBDatasetPrecheckScanRun)
        .filter(
            DBDatasetPrecheckScanRun.id == scan_run_id,
            DBDatasetPrecheckScanRun.tenant_id == tenant_id,
            DBDatasetPrecheckScanRun.dataset_id == dataset_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail=_SCAN_RUN_NOT_FOUND_DETAIL)

    raw = load_precheck_near_dups_from_row(row, tenant_id=tenant_id)
    try:
        return DatasetPrecheckNearDupResponse(**raw)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"Invalid near-dup payload: {str(exc)[:200]}") from exc


@router.get(
    "/{dataset_id}/precheck/scan-runs/{scan_run_id}/diff",
    response_model=DatasetPrecheckDiffResponse,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def diff_dataset_precheck_scan_runs(
    dataset_id: UUID,
    scan_run_id: UUID,
    base_scan_run_id: Annotated[UUID, Query(..., description='Base scan run id to compare against')],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    get_dataset_for_precheck(db, tenant_id=tenant_id, dataset_id=dataset_id, account_id=account_id, require_write=False)

    base = (
        db.query(DBDatasetPrecheckScanRun)
        .filter(
            DBDatasetPrecheckScanRun.id == base_scan_run_id,
            DBDatasetPrecheckScanRun.tenant_id == tenant_id,
            DBDatasetPrecheckScanRun.dataset_id == dataset_id,
        )
        .first()
    )
    if base is None:
        raise HTTPException(status_code=404, detail="Base scan run not found")
    target = (
        db.query(DBDatasetPrecheckScanRun)
        .filter(
            DBDatasetPrecheckScanRun.id == scan_run_id,
            DBDatasetPrecheckScanRun.tenant_id == tenant_id,
            DBDatasetPrecheckScanRun.dataset_id == dataset_id,
        )
        .first()
    )
    if target is None:
        raise HTTPException(status_code=404, detail="Target scan run not found")

    base_summary = getattr(base, "summary", None)
    base_summary = base_summary if isinstance(base_summary, dict) else {}
    target_summary = getattr(target, "summary", None)
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
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
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
    dataset = get_dataset_for_precheck(db, tenant_id=tenant_id, dataset_id=dataset_id, account_id=account_id, require_write=False)
    before_policy = parse_ingestion_policy_from_metadata(dict(getattr(dataset, "dataset_metadata", None) or {}))
    row = (
        db.query(DBDatasetPrecheckScanRun)
        .filter(
            DBDatasetPrecheckScanRun.id == scan_run_id,
            DBDatasetPrecheckScanRun.tenant_id == tenant_id,
            DBDatasetPrecheckScanRun.dataset_id == dataset_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail=_SCAN_RUN_NOT_FOUND_DETAIL)
    suggestion = build_ingestion_policy_suggestion(
        row,
        tenant_id=tenant_id,
        before_policy=before_policy,
        max_names_per_bucket=int(max_names_per_bucket or 0),
    )
    return DatasetPrecheckIngestionSuggestionResponse(**suggestion)


@router.post(
    "/{dataset_id}/precheck/scan-runs/{scan_run_id}/apply-ingestion-policy",
    response_model=IngestionPolicyImportResponse,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def apply_dataset_precheck_ingestion_policy_suggestion(
    dataset_id: UUID,
    scan_run_id: UUID,
    replace: Annotated[bool, Query(description='Whether to overwrite existing dataset ingestion_policy')] = False,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    # Applying modifies dataset metadata -> require write permission.
    dataset = get_dataset_for_precheck(db, tenant_id=tenant_id, dataset_id=dataset_id, account_id=account_id, require_write=True)
    row = (
        db.query(DBDatasetPrecheckScanRun)
        .filter(
            DBDatasetPrecheckScanRun.id == scan_run_id,
            DBDatasetPrecheckScanRun.tenant_id == tenant_id,
            DBDatasetPrecheckScanRun.dataset_id == dataset_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail=_SCAN_RUN_NOT_FOUND_DETAIL)

    res = apply_ingestion_policy_suggestion(
        db,
        dataset=dataset,
        scan_run=row,
        tenant_id=tenant_id,
        replace=bool(replace),
    )
    return IngestionPolicyImportResponse(**res)


@router.get("/{dataset_id}/precheck/scan-runs/{scan_run_id}/export", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def export_dataset_precheck_summary_json(
    dataset_id: UUID,
    scan_run_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    get_dataset_for_precheck(db, tenant_id=tenant_id, dataset_id=dataset_id, account_id=account_id, require_write=False)
    row = (
        db.query(DBDatasetPrecheckScanRun)
        .filter(
            DBDatasetPrecheckScanRun.id == scan_run_id,
            DBDatasetPrecheckScanRun.tenant_id == tenant_id,
            DBDatasetPrecheckScanRun.dataset_id == dataset_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail=_SCAN_RUN_NOT_FOUND_DETAIL)

    summary = load_precheck_summary_from_row(row)
    content = json.dumps(summary.model_dump(), ensure_ascii=False, separators=(",", ":"))
    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "_", f"dataset_{dataset_id}")[:64]
    filename = f"{safe}.precheck.json"
    return Response(
        content=content,
        media_type="application/json",
        headers=download_response_headers(filename),
    )


@router.get("/{dataset_id}/precheck/scan-runs/{scan_run_id}/export-html", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def export_dataset_precheck_html_report(
    dataset_id: UUID,
    scan_run_id: UUID,
    redact: Annotated[bool, Query(description='Whether to redact dataset/path for sharing')] = True,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    dataset = get_dataset_for_precheck(db, tenant_id=tenant_id, dataset_id=dataset_id, account_id=account_id, require_write=False)

    row = (
        db.query(DBDatasetPrecheckScanRun)
        .filter(
            DBDatasetPrecheckScanRun.id == scan_run_id,
            DBDatasetPrecheckScanRun.tenant_id == tenant_id,
            DBDatasetPrecheckScanRun.dataset_id == dataset_id,
        )
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail=_SCAN_RUN_NOT_FOUND_DETAIL)

    cfg = getattr(row, "config", None)
    cfg = cfg if isinstance(cfg, dict) else {}
    artifacts = getattr(row, "artifacts", None)
    artifacts = artifacts if isinstance(artifacts, dict) else {}

    summary = load_precheck_summary_from_row(row)
    effective_redact = bool(redact) or bool(cfg.get("redact_paths", False))
    root_path = str(artifacts.get("root_path") or "")

    samples = None
    # Only include file lists in a redacted export when the scan itself redacted paths
    # (avoid leaking real filenames via an on-demand rebuild).
    if (not effective_redact) or bool(cfg.get("redact_paths", False)):
        try:
            samples = load_precheck_samples_from_row(
                row,
                tenant_id=tenant_id,
                size=int(cfg.get("sample_size") or 0),
                prefer_artifact=True,
            )
        except Exception:
            samples = None

    html = render_precheck_html(
        title="MimirQ · 预检扫描报告",
        dataset_name=str(getattr(dataset, "name", "") or ""),
        dataset_id=str(dataset_id),
        root_path=root_path,
        generated_at=summary.generated_at,
        summary=summary.model_dump(),
        samples=samples,
        redact=effective_redact,
    )

    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(getattr(dataset, "name", "") or "dataset"))[:64]
    filename = f"{safe}.precheck.html"
    return Response(
        content=html,
        media_type="text/html; charset=utf-8",
        headers=download_response_headers(filename),
    )
