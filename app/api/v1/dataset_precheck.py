"""
Dataset precheck scan API.

Precheck scans are intended for "before ingestion" analysis on a local folder.
They are run-based (async), store progress in DB, and store per-file records on disk.
"""

from __future__ import annotations

import json
import re
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.dataset_precheck import (
    DatasetPrecheckFindingListResponse,
    DatasetPrecheckScanRunCreateRequest,
    DatasetPrecheckScanRunListResponse,
    DatasetPrecheckScanRunOut,
    DatasetPrecheckSummary,
)
from app.core.database import SessionLocal, get_db
from app.models.dataset_precheck_scan import DatasetPrecheckScanRun as DBDatasetPrecheckScanRun
from app.services.dataset_precheck_service import _scan_run_out_from_row, get_dataset_for_precheck, list_precheck_finding_files, load_precheck_summary_from_row
from app.services.dataset_precheck_scan_runner import run_dataset_precheck_scan
from app.services.report_html import render_precheck_html
from app.tasks.queue import enqueue_dataset_precheck_scan

router = APIRouter()


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
        except Exception:
            pass
    finally:
        db.close()


@router.post("/{dataset_id}/precheck/scan-runs", response_model=DatasetPrecheckScanRunOut, status_code=201)
async def create_dataset_precheck_scan_run(
    dataset_id: UUID,
    body: DatasetPrecheckScanRunCreateRequest,
    background_tasks: BackgroundTasks,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
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


@router.get("/{dataset_id}/precheck/scan-runs", response_model=DatasetPrecheckScanRunListResponse)
def list_dataset_precheck_scan_runs(
    dataset_id: UUID,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=200),
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
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


@router.get("/{dataset_id}/precheck/scan-runs/{scan_run_id}", response_model=DatasetPrecheckScanRunOut)
def get_dataset_precheck_scan_run(
    dataset_id: UUID,
    scan_run_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
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
        raise HTTPException(status_code=404, detail="Scan run not found")
    return DatasetPrecheckScanRunOut(**_scan_run_out_from_row(row))


@router.get("/{dataset_id}/precheck/scan-runs/{scan_run_id}/summary", response_model=DatasetPrecheckSummary)
def get_dataset_precheck_summary(
    dataset_id: UUID,
    scan_run_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
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
        raise HTTPException(status_code=404, detail="Scan run not found")
    return load_precheck_summary_from_row(row)


@router.get(
    "/{dataset_id}/precheck/scan-runs/{scan_run_id}/findings/{finding_key}",
    response_model=DatasetPrecheckFindingListResponse,
)
def list_dataset_precheck_finding_files(
    dataset_id: UUID,
    scan_run_id: UUID,
    finding_key: str,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
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


@router.get("/{dataset_id}/precheck/scan-runs/{scan_run_id}/export")
def export_dataset_precheck_summary_json(
    dataset_id: UUID,
    scan_run_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
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
        raise HTTPException(status_code=404, detail="Scan run not found")

    summary = load_precheck_summary_from_row(row)
    content = json.dumps(summary.model_dump(), ensure_ascii=False, separators=(",", ":"))
    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "_", f"dataset_{dataset_id}")[:64]
    filename = f"{safe}.precheck.json"
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename=\"{filename}\"'},
    )


@router.get("/{dataset_id}/precheck/scan-runs/{scan_run_id}/export-html")
def export_dataset_precheck_html_report(
    dataset_id: UUID,
    scan_run_id: UUID,
    redact: bool = Query(default=True, description="Whether to redact dataset/path for sharing"),
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
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
        raise HTTPException(status_code=404, detail="Scan run not found")

    cfg = getattr(row, "config", None)
    cfg = cfg if isinstance(cfg, dict) else {}
    artifacts = getattr(row, "artifacts", None)
    artifacts = artifacts if isinstance(artifacts, dict) else {}

    summary = load_precheck_summary_from_row(row)
    effective_redact = bool(redact) or bool(cfg.get("redact_paths", False))
    root_path = str(artifacts.get("root_path") or "")

    html = render_precheck_html(
        title="MimirQ · 预检扫描报告",
        dataset_name=str(getattr(dataset, "name", "") or ""),
        dataset_id=str(dataset_id),
        root_path=root_path,
        generated_at=summary.generated_at,
        summary=summary.model_dump(),
        redact=effective_redact,
    )

    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "_", str(getattr(dataset, "name", "") or "dataset"))[:64]
    filename = f"{safe}.precheck.html"
    return Response(
        content=html,
        media_type="text/html; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename=\"{filename}\"'},
    )
