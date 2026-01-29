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
    UrlBatchConnectorConfig,
    WebCrawlConnectorConfig,
)
from app.api.v1.documents import UrlUploadRequest, _ingest_url_upload_request, _resolve_writable_dataset
from app.core.config import settings
from app.core.database import SessionLocal, get_db
from app.core.secrets import decrypt_connector_config_secrets, encrypt_connector_config_secrets, redact_secrets
from app.models.connector import ConnectorRun, ConnectorRunDocument
from app.services.dataset_service import DatasetService
from app.services.document_permission_service import DocumentPermissionService
from app.services.web_crawler import crawl_site

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
        config=redact_secrets(dict(run.config or {})),
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
        ),
        ConnectorInfo(
            id="web_crawl",
            name="网站抓取（站点级）",
            description="从站点种子 URL 开始抓取链接并批量入库（支持 Cookie/Bearer/Basic 登录态；配置中的密钥会被加密存储并在响应中脱敏）",
            supports_incremental=False,
        ),
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


def _build_auth_headers(cfg: dict) -> dict[str, str]:
    auth = cfg.get("auth") if isinstance(cfg.get("auth"), dict) else None
    if not isinstance(auth, dict):
        return {}
    t = str(auth.get("type") or "none").strip().lower()
    if t == "cookie":
        cookie = str(auth.get("cookie") or "").strip()
        return {"Cookie": cookie} if cookie else {}
    if t == "bearer":
        token = str(auth.get("token") or "").strip()
        return {"Authorization": f"Bearer {token}"} if token else {}
    if t == "basic":
        import base64

        username = str(auth.get("username") or "").strip()
        password = str(auth.get("password") or "").strip()
        if not username or not password:
            return {}
        raw = f"{username}:{password}".encode("utf-8", "ignore")
        b64 = base64.b64encode(raw).decode("ascii")
        return {"Authorization": f"Basic {b64}"}
    return {}


async def _execute_web_crawl_run(*, run_id: UUID, tenant_id: UUID, requested_by: str) -> None:
    """
    Background execution for web_crawl connector.

    Flow:
    - Crawl start_urls and discover links (bounded by max_pages/max_depth)
    - Ingest each discovered URL using the existing /documents/upload-url path
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

        cfg_raw = dict(run.config or {})
        cfg = decrypt_connector_config_secrets(cfg_raw)

        start_urls = cfg.get("start_urls") if isinstance(cfg.get("start_urls"), list) else []
        start_urls = [str(u or "").strip() for u in start_urls if str(u or "").strip()]
        max_pages = int(cfg.get("max_pages") or 50)
        max_depth = int(cfg.get("max_depth") or 3)
        same_host_only = bool(cfg.get("same_host_only", True))
        include_patterns = cfg.get("include_patterns") if isinstance(cfg.get("include_patterns"), list) else []
        exclude_patterns = cfg.get("exclude_patterns") if isinstance(cfg.get("exclude_patterns"), list) else []
        user_agent = cfg.get("user_agent") if isinstance(cfg.get("user_agent"), str) else None

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

        auth_headers = _build_auth_headers(cfg)

        crawl = await crawl_site(
            start_urls=start_urls,
            max_pages=max_pages,
            max_depth=max_depth,
            same_host_only=same_host_only,
            include_patterns=[str(p or "") for p in include_patterns if str(p or "").strip()],
            exclude_patterns=[str(p or "") for p in exclude_patterns if str(p or "").strip()],
            headers=auth_headers,
            user_agent=user_agent,
            timeout_sec=float(getattr(settings, "URL_INGEST_TIMEOUT_SEC", 30.0) or 30.0),
            max_bytes=int(getattr(settings, "URL_INGEST_MAX_BYTES", 0) or settings.MAX_FILE_SIZE),
            follow_redirects=bool(getattr(settings, "URL_INGEST_FOLLOW_REDIRECTS", False)),
        )

        created = 0
        failed = 0
        created_doc_ids: list[UUID] = []

        stats = dict(run.stats or {})
        stats.update({"visited": int(crawl.visited), "queued": int(crawl.queued), "discovered": int(len(crawl.urls))})
        if crawl.errors:
            stats["crawl_errors"] = list(crawl.errors)[:20]
        run.stats = stats
        db.commit()

        for url in crawl.urls:
            if str(run.status or "").lower() == "cancelled":
                break

            try:
                body = UrlUploadRequest(
                    url=url,
                    dataset_id=run.dataset_id,
                    filename=filename,
                    fetch_headers=auth_headers or None,
                    user_agent=user_agent,
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
                        document_id=doc.id,
                        owner_id=requested_by,
                        member_ids=access_members,
                    )

                db.add(
                    ConnectorRunDocument(
                        tenant_id=tenant_id,
                        run_id=run.id,
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
                errs = (run.stats or {}).get("errors")
                if not isinstance(errs, list):
                    errs = []
                if len(errs) < 20:
                    errs.append({"url": url, "error": str(exc)[:200]})
                stats = dict(run.stats or {})
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

    connector_id = str(payload.connector_id or "").strip()
    if connector_id == "url_batch":
        cfg = UrlBatchConnectorConfig.model_validate(payload.config or {})
        cfg_dict = cfg.model_dump(exclude_none=True)
    elif connector_id == "web_crawl":
        cfg = WebCrawlConnectorConfig.model_validate(payload.config or {})
        cfg_dict = encrypt_connector_config_secrets(cfg.model_dump(exclude_none=True))
    else:
        raise HTTPException(status_code=400, detail="Unsupported connector_id")

    run = ConnectorRun(
        tenant_id=tenant_id,
        dataset_id=dataset.id,
        connector_id=connector_id,
        requested_by=account_id,
        status="pending",
        config=cfg_dict,
        stats={},
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    # Execute asynchronously after response.
    if connector_id == "url_batch":
        background_tasks.add_task(_execute_url_batch_run, run_id=run.id, tenant_id=tenant_id, requested_by=account_id)
    else:
        background_tasks.add_task(_execute_web_crawl_run, run_id=run.id, tenant_id=tenant_id, requested_by=account_id)

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
