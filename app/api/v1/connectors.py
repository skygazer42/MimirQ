"""
Connector API (enterprise ingestion framework).

This is a minimal v1 implementation focused on:
- URL batch ingestion as the first connector
- Run tracking (status/stats/error)
"""

from __future__ import annotations

import contextlib
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session, selectinload

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.connector import (
    ConnectorInfo,
    ConnectorRunCreateRequest,
    ConnectorRunListResponse,
    ConnectorRunOut,
)
from app.api.v1.documents import UrlUploadRequest, _ingest_url_upload_request, _resolve_writable_dataset
from app.core.config import settings
from app.core.database import SessionLocal, get_db
from app.models.connector import ConnectorRun, ConnectorRunDocument
from app.services.dataset_service import DatasetService
from app.services.document_permission_service import DocumentPermissionService


router = APIRouter()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _run_out(run: ConnectorRun) -> ConnectorRunOut:
    docs = getattr(run, "documents", None) or []
    return ConnectorRunOut(
        id=run.id,
        tenant_id=run.tenant_id,
        dataset_id=run.dataset_id,
        connector_id=str(run.connector_id or ""),
        requested_by=(run.requested_by or None),
        status=str(run.status or "pending"),  # type: ignore[arg-type]
        config=dict(run.config or {}),
        stats=dict(run.stats or {}),
        error_message=(run.error_message or None),
        task_id=(run.task_id or None),
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        documents=[
            {
                "document_id": d.document_id,
                "source_ref": (d.source_ref or None),
                "status": str(d.status or "created"),
            }
            for d in docs
        ],
    )


@router.get("", response_model=list[ConnectorInfo])
def list_connectors() -> list[ConnectorInfo]:
    """List available connectors (static registry)."""
    return [
        ConnectorInfo(
            id="url_batch",
            name="URL 批量导入",
            description="从多个 http(s) URL 拉取内容并入库（支持 URL_INGEST_* 安全开关）",
            supports_incremental=False,
        )
    ]


async def _execute_url_batch_run(*, run_id: UUID, tenant_id: UUID, requested_by: str) -> None:
    """
    Background execution for url_batch connector.

    Notes:
    - Runs in API process (FastAPI BackgroundTasks). If TASK_QUEUE is enabled, document processing is queued;
      otherwise documents are processed inline (async) within this background task.
    """
    db = SessionLocal()
    try:
        run = (
            db.query(ConnectorRun)
            .options(selectinload(ConnectorRun.documents))
            .filter(ConnectorRun.id == run_id, ConnectorRun.tenant_id == tenant_id)
            .first()
        )
        if not run:
            return
        if str(run.status or "").lower() in {"cancelled", "completed", "failed"}:
            return

        run.status = "running"
        run.started_at = _now()
        run.error_message = None
        run.stats = dict(run.stats or {})
        db.commit()
        db.refresh(run)

        cfg = dict(run.config or {})
        urls = cfg.get("urls") if isinstance(cfg.get("urls"), list) else []
        filename = cfg.get("filename") if isinstance(cfg.get("filename"), str) else None
        parser_backend = cfg.get("parser_backend") if isinstance(cfg.get("parser_backend"), str) else "auto"
        chunk_strategy = cfg.get("chunk_strategy") if isinstance(cfg.get("chunk_strategy"), str) else "langchain_recursive"
        pipeline = cfg.get("pipeline") if isinstance(cfg.get("pipeline"), dict) else None
        access = cfg.get("access") if isinstance(cfg.get("access"), dict) else None

        access_mode = str(access.get("mode") or "inherit").strip().lower() if isinstance(access, dict) else "inherit"
        access_members = access.get("partial_member_list") if isinstance(access, dict) else None
        if not isinstance(access_members, list):
            access_members = []
        access_members = [str(v).strip() for v in access_members if isinstance(v, (str, int, float)) and str(v).strip()]

        created = 0
        failed = 0
        created_doc_ids: list[UUID] = []

        for raw in urls:
            if str(run.status or "").lower() == "cancelled":
                break

            url = str(raw or "").strip()
            if not url:
                continue

            try:
                body = UrlUploadRequest(
                    url=url,
                    dataset_id=run.dataset_id,
                    filename=filename,
                    parser_backend=parser_backend,
                    chunk_strategy=chunk_strategy,
                    pipeline=pipeline,  # type: ignore[arg-type]
                )
                doc = await _ingest_url_upload_request(
                    background_tasks=None,
                    body=body,
                    tenant_id=tenant_id,
                    account_id=requested_by,
                    db=db,
                )

                # Apply document-level ACL overrides for connector-created docs (no impact on pipeline_hash).
                doc.access_mode = None if access_mode == "inherit" else access_mode
                if not (getattr(doc, "owner_id", None) or "").strip():
                    doc.owner_id = requested_by

                if access_mode == "partial_members":
                    DocumentPermissionService.update_partial_member_list(
                        db,
                        tenant_id,
                        doc.id,
                        list(access_members),
                    )
                else:
                    DocumentPermissionService.clear_partial_member_list(db, tenant_id, doc.id)

                db.add(
                    ConnectorRunDocument(
                        tenant_id=tenant_id,
                        run_id=run_id,
                        document_id=doc.id,
                        source_ref=url,
                        status="created",
                    )
                )
                db.commit()

                created += 1
                created_doc_ids.append(doc.id)
            except Exception as exc:  # noqa: BLE001
                failed += 1
                # Keep going; record a truncated error in stats.
                stats = dict(run.stats or {})
                errs = stats.get("errors")
                if not isinstance(errs, list):
                    errs = []
                if len(errs) < 20:
                    errs.append({"url": url, "error": str(exc)[:200]})
                stats["errors"] = errs
                run.stats = stats
                db.commit()

        stats = dict(run.stats or {})
        stats.update({"created": int(created), "failed": int(failed), "document_ids": [str(d) for d in created_doc_ids]})
        run.stats = stats
        run.finished_at = _now()
        run.status = "completed" if failed == 0 else ("failed" if created == 0 else "completed")
        db.commit()
    except Exception as exc:  # noqa: BLE001
        with contextlib.suppress(Exception):
            run = (
                db.query(ConnectorRun)
                .filter(ConnectorRun.id == run_id, ConnectorRun.tenant_id == tenant_id)
                .first()
            )
            if run is not None:
                run.status = "failed"
                run.finished_at = _now()
                run.error_message = str(exc)[:200]
                db.commit()
    finally:
        db.close()


@router.post("/runs", response_model=ConnectorRunOut, status_code=201)
async def create_connector_run(
    payload: ConnectorRunCreateRequest,
    background_tasks: BackgroundTasks,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """
    Create a connector run (currently supports url_batch).

    Requires dataset write permission.
    """
    if not bool(getattr(settings, "URL_INGEST_ENABLED", False)):
        raise HTTPException(status_code=400, detail="URL ingestion is disabled")

    DatasetService.ensure_member(db, tenant_id, account_id)
    dataset = _resolve_writable_dataset(db, tenant_id, account_id, payload.dataset_id)

    run = ConnectorRun(
        tenant_id=tenant_id,
        dataset_id=dataset.id,
        connector_id=str(payload.connector_id),
        requested_by=account_id,
        status="pending",
        config=payload.config.model_dump(exclude_none=True),
        stats={},
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    # Execute asynchronously after response.
    background_tasks.add_task(_execute_url_batch_run, run_id=run.id, tenant_id=tenant_id, requested_by=account_id)

    return _run_out(run)


@router.get("/runs", response_model=ConnectorRunListResponse)
def list_connector_runs(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=200),
    dataset_id: UUID | None = None,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """List connector runs (requires dataset write permission for each returned run's dataset)."""
    DatasetService.ensure_member(db, tenant_id, account_id)

    query = db.query(ConnectorRun).filter(ConnectorRun.tenant_id == tenant_id)
    if dataset_id:
        dataset = DatasetService.get_dataset(db, tenant_id, dataset_id)
        DatasetService.assert_dataset_writable(db, dataset, account_id)
        query = query.filter(ConnectorRun.dataset_id == dataset_id)

    total = int(query.count())
    runs = (
        query.options(selectinload(ConnectorRun.documents))
        .order_by(ConnectorRun.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    # If dataset_id isn't provided, filter to writable datasets only (avoid leaking URLs/config to readers).
    if not dataset_id:
        allowed: list[ConnectorRun] = []
        for run in runs:
            if not run.dataset_id:
                continue
            try:
                ds = DatasetService.get_dataset(db, tenant_id, run.dataset_id)
                DatasetService.assert_dataset_writable(db, ds, account_id)
            except HTTPException:
                continue
            allowed.append(run)
        runs = allowed

    return {"total": total, "items": [_run_out(r) for r in runs]}


@router.get("/runs/{run_id}", response_model=ConnectorRunOut)
def get_connector_run(
    run_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """Get connector run detail (requires dataset write permission)."""
    DatasetService.ensure_member(db, tenant_id, account_id)

    run = (
        db.query(ConnectorRun)
        .options(selectinload(ConnectorRun.documents))
        .filter(ConnectorRun.id == run_id, ConnectorRun.tenant_id == tenant_id)
        .first()
    )
    if not run:
        raise HTTPException(status_code=404, detail="Connector run not found")

    if run.dataset_id:
        ds = DatasetService.get_dataset(db, tenant_id, run.dataset_id)
        DatasetService.assert_dataset_writable(db, ds, account_id)

    return _run_out(run)


@router.post("/runs/{run_id}/cancel", response_model=ConnectorRunOut)
def cancel_connector_run(
    run_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """Cancel a running connector run (best-effort)."""
    DatasetService.ensure_member(db, tenant_id, account_id)

    run = db.query(ConnectorRun).filter(ConnectorRun.id == run_id, ConnectorRun.tenant_id == tenant_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Connector run not found")

    if run.dataset_id:
        ds = DatasetService.get_dataset(db, tenant_id, run.dataset_id)
        DatasetService.assert_dataset_writable(db, ds, account_id)

    status = str(run.status or "").lower()
    if status in {"completed", "failed"}:
        return _run_out(run)

    run.status = "cancelled"
    run.finished_at = _now()
    db.commit()
    db.refresh(run)
    return _run_out(run)
