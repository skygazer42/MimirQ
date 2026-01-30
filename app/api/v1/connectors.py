"""
Connector API (enterprise ingestion framework).

This is a minimal v1 implementation focused on:
- URL batch ingestion as the first connector
- Run tracking (status/stats/error)
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response
import httpx
from sqlalchemy.orm import Session, selectinload

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.connector import (
    ConnectorInfo,
    ConnectorConfigCreateRequest,
    ConnectorConfigListResponse,
    ConnectorConfigOut,
    ConnectorConfigUpdateRequest,
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
from app.models.connector_config import ConnectorConfig
from app.services.dataset_service import DatasetService
from app.services.document_permission_service import DocumentPermissionService
from app.services.web_crawler import crawl_site

router = APIRouter()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_error_str(exc: Exception) -> str:
    msg = str(exc or "").replace("\r", " ").replace("\n", " ").strip()
    if not msg:
        msg = exc.__class__.__name__
    if len(msg) > 200:
        msg = msg[:200]
    return msg


def _classify_connector_error(exc: Exception) -> tuple[str, str]:
    """
    Best-effort error classifier for connector runs.

    The goal is to group similar failures for UI/operator visibility; it is not used for control flow.
    """
    if isinstance(exc, HTTPException):
        detail = str(getattr(exc, "detail", "") or "").strip()
        msg = (detail or f"HTTP {getattr(exc, 'status_code', 0)}").replace("\r", " ").replace("\n", " ").strip()
        msg = msg[:200] if len(msg) > 200 else msg
        code = f"http_{getattr(exc, 'status_code', 0)}"
        lowered = msg.lower()
        if "not allowed" in lowered or "private ip" in lowered or "ssrf" in lowered:
            code = "ssrf"
        elif "timeout" in lowered:
            code = "timeout"
        elif getattr(exc, "status_code", None) == 413:
            code = "too_large"
        elif getattr(exc, "status_code", None) == 400:
            code = "bad_request"
        return code, msg

    if isinstance(exc, (asyncio.TimeoutError, httpx.TimeoutException)):
        return "timeout", _safe_error_str(exc) or "timeout"

    msg = _safe_error_str(exc)
    lowered = msg.lower()
    if "timeout" in lowered:
        return "timeout", msg
    if "not allowed" in lowered or "private ip" in lowered or "ssrf" in lowered:
        return "ssrf", msg
    return "error", msg


def _append_connector_error(stats: dict, *, url: str, exc: Exception) -> dict:
    code, msg = _classify_connector_error(exc)

    # Sample errors (bounded) for UI quick display.
    errs = stats.get("errors")
    if not isinstance(errs, list):
        errs = []
    if len(errs) < 20:
        errs.append({"url": url, "code": code, "error": msg})
    stats["errors"] = errs

    failed_urls = stats.get("failed_urls")
    if not isinstance(failed_urls, list):
        failed_urls = []
    if url and url not in failed_urls:
        failed_urls.append(url)
    stats["failed_urls"] = failed_urls

    groups = stats.get("error_groups")
    if not isinstance(groups, list):
        groups = []
    key = f"{code}:{msg}"
    group = None
    for it in groups:
        if isinstance(it, dict) and str(it.get("key") or "") == key:
            group = it
            break
    if group is None:
        group = {"key": key, "code": code, "error": msg, "count": 0, "sample_urls": []}
        groups.append(group)
    group["count"] = int(group.get("count", 0) or 0) + 1
    sample_urls = group.get("sample_urls")
    if not isinstance(sample_urls, list):
        sample_urls = []
    if url and url not in sample_urls and len(sample_urls) < 3:
        sample_urls.append(url)
    group["sample_urls"] = sample_urls
    stats["error_groups"] = groups

    return stats


def _finalize_connector_stats(stats: dict) -> dict:
    groups = stats.get("error_groups")
    if isinstance(groups, list):
        def _count(it: object) -> int:
            if not isinstance(it, dict):
                return 0
            return int(it.get("count", 0) or 0)

        groups_sorted = sorted(groups, key=_count, reverse=True)
        # Keep `key` for stable grouping across incremental updates, but it is optional for the UI.
        stats["error_groups"] = groups_sorted
    return stats


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


def _config_out(cfg: ConnectorConfig) -> ConnectorConfigOut:
    return ConnectorConfigOut(
        id=cfg.id,
        tenant_id=cfg.tenant_id,
        dataset_id=cfg.dataset_id,
        connector_id=str(cfg.connector_id or ""),
        name=str(cfg.name or ""),
        enabled=bool(cfg.enabled),
        schedule_cron=(str(cfg.schedule_cron).strip() if isinstance(cfg.schedule_cron, str) and cfg.schedule_cron.strip() else None),
        config=redact_secrets(dict(cfg.config or {})),
        state=dict(cfg.state or {}),
        last_run_at=(cfg.last_run_at or None),
        last_error=(cfg.last_error or None),
        created_at=cfg.created_at,
        updated_at=cfg.updated_at,
    )


def _schedule_due(*, schedule: str, now: datetime, last_run_at: datetime | None) -> bool:
    """
    Best-effort cron-like evaluator for the scheduled tick hook.

    Supported (minimal) formats:
      - "@hourly" / "@daily" / "@weekly" / "@monthly"
      - "*/N * * * *" (every N minutes)

    Unknown formats are treated as not-due.
    """
    s = str(schedule or "").strip().lower()
    if not s:
        return False

    def _elapsed_sec() -> float:
        if last_run_at is None:
            # Never ran -> due.
            return 10**18
        try:
            return (now - last_run_at).total_seconds()
        except Exception:
            return 10**18

    if s in {"@hourly"}:
        return _elapsed_sec() >= 60 * 60
    if s in {"@daily"}:
        return _elapsed_sec() >= 60 * 60 * 24
    if s in {"@weekly"}:
        return _elapsed_sec() >= 60 * 60 * 24 * 7
    if s in {"@monthly"}:
        # Best-effort: treat month as 30 days.
        return _elapsed_sec() >= 60 * 60 * 24 * 30

    parts = s.split()
    if len(parts) == 5 and parts[0].startswith("*/"):
        raw = parts[0][2:]
        try:
            n = max(1, int(raw))
        except Exception:
            return False
        return _elapsed_sec() >= 60 * n

    return False


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

        cfg_raw = dict(run.config or {})
        cfg = decrypt_connector_config_secrets(cfg_raw)
        urls = cfg.get("urls") if isinstance(cfg.get("urls"), list) else []
        urls = [str(u or "").strip() for u in urls if str(u or "").strip()]
        filename = cfg.get("filename") if isinstance(cfg.get("filename"), str) else None
        user_agent = cfg.get("user_agent") if isinstance(cfg.get("user_agent"), str) else None
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

        created = 0
        failed = 0
        created_doc_ids: list[UUID] = []

        stats0 = dict(run.stats or {})
        stats0.update(
            {
                "total_urls": int(len(urls)),
                "processed_urls": 0,
                "cursor": 0,
                "created": 0,
                "failed": 0,
                "failed_urls": [],
                "errors": [],
                "error_groups": [],
            }
        )
        run.stats = stats0
        db.commit()

        for idx, url in enumerate(urls):
            # Observe cancellation from another DB session (best-effort).
            try:
                db.refresh(run)
            except Exception:
                pass
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
                created += 1
                created_doc_ids.append(doc.id)
            except Exception as exc:  # noqa: BLE001
                failed += 1
                stats = dict(run.stats or {})
                stats = _append_connector_error(stats, url=url, exc=exc)
                run.stats = stats
            finally:
                processed = idx + 1
                stats = dict(run.stats or {})
                stats.update(
                    {
                        "total_urls": int(len(urls)),
                        "processed_urls": int(processed),
                        "cursor": int(processed),
                        "created": int(created),
                        "failed": int(failed),
                        "document_ids": [str(d) for d in created_doc_ids],
                    }
                )
                run.stats = _finalize_connector_stats(stats)
                db.commit()

        # Finalize status (don't override cancellation).
        try:
            db.refresh(run)
        except Exception:
            pass
        if str(run.status or "").lower() == "cancelled":
            if run.finished_at is None:
                run.finished_at = _now()
            run.stats = _finalize_connector_stats(dict(run.stats or {}))
            db.commit()
            return

        stats = dict(run.stats or {})
        stats.update({"document_ids": [str(d) for d in created_doc_ids]})
        run.stats = _finalize_connector_stats(stats)
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
        use_sitemaps = bool(cfg.get("use_sitemaps", False))
        sitemap_urls = cfg.get("sitemap_urls") if isinstance(cfg.get("sitemap_urls"), list) else []
        respect_robots = bool(cfg.get("respect_robots", False))
        dedup_canonical = bool(cfg.get("dedup_canonical", True))
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
            use_sitemaps=use_sitemaps,
            sitemap_urls=[str(u or "") for u in sitemap_urls if str(u or "").strip()],
            respect_robots=respect_robots,
            dedup_canonical=dedup_canonical,
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
        stats.update(
            {
                "visited": int(crawl.visited),
                "queued": int(crawl.queued),
                "discovered": int(len(crawl.urls)),
                "total_urls": int(len(crawl.urls)),
                "processed_urls": 0,
                "cursor": 0,
                "created": 0,
                "failed": 0,
                "failed_urls": [],
                "errors": [],
                "error_groups": [],
            }
        )
        if crawl.errors:
            stats["crawl_errors"] = list(crawl.errors)[:20]
        run.stats = _finalize_connector_stats(stats)
        db.commit()

        for idx, url in enumerate(crawl.urls):
            # Observe cancellation from another DB session (best-effort).
            try:
                db.refresh(run)
            except Exception:
                pass
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
                else:
                    DocumentPermissionService.clear_partial_member_list(db, tenant_id, doc.id)

                db.add(
                    ConnectorRunDocument(
                        tenant_id=tenant_id,
                        run_id=run.id,
                        document_id=doc.id,
                        source_ref=url,
                        status="created",
                    )
                )
                created += 1
                created_doc_ids.append(doc.id)
            except Exception as exc:  # noqa: BLE001
                failed += 1
                stats = dict(run.stats or {})
                stats = _append_connector_error(stats, url=url, exc=exc)
                run.stats = stats
            finally:
                processed = idx + 1
                stats = dict(run.stats or {})
                stats.update(
                    {
                        "total_urls": int(len(crawl.urls)),
                        "processed_urls": int(processed),
                        "cursor": int(processed),
                        "created": int(created),
                        "failed": int(failed),
                        "document_ids": [str(d) for d in created_doc_ids],
                    }
                )
                run.stats = _finalize_connector_stats(stats)
                db.commit()

        # Finalize status (don't override cancellation).
        try:
            db.refresh(run)
        except Exception:
            pass
        if str(run.status or "").lower() == "cancelled":
            if run.finished_at is None:
                run.finished_at = _now()
            run.stats = _finalize_connector_stats(dict(run.stats or {}))
            db.commit()
            return

        stats = dict(run.stats or {})
        stats.update({"document_ids": [str(d) for d in created_doc_ids]})
        run.stats = _finalize_connector_stats(stats)
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
        cfg_dict = encrypt_connector_config_secrets(cfg.model_dump(exclude_none=True))
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


def _extract_failed_urls(stats: dict) -> list[str]:
    urls: list[str] = []
    raw_failed = stats.get("failed_urls")
    if isinstance(raw_failed, list):
        urls = [str(u or "").strip() for u in raw_failed if str(u or "").strip()]
    if not urls:
        raw_errors = stats.get("errors")
        if isinstance(raw_errors, list):
            urls = [str((e or {}).get("url") or "").strip() for e in raw_errors if isinstance(e, dict)]
            urls = [u for u in urls if u]
    # Dedupe while preserving order.
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out


@router.post("/runs/{run_id}/retry-failed", response_model=ConnectorRunOut, status_code=201)
async def retry_failed_connector_run(
    run_id: UUID,
    background_tasks: BackgroundTasks,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """Create a new connector run that retries only the failed URLs (best-effort)."""
    if not bool(getattr(settings, "URL_INGEST_ENABLED", False)):
        raise HTTPException(status_code=400, detail="URL ingestion is disabled")

    DatasetService.ensure_member(db, tenant_id, account_id)

    run = db.query(ConnectorRun).filter(ConnectorRun.id == run_id, ConnectorRun.tenant_id == tenant_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Connector run not found")

    status = str(run.status or "").lower()
    if status in {"pending", "running"}:
        raise HTTPException(status_code=400, detail="Connector run is still active")

    if run.dataset_id:
        ds = DatasetService.get_dataset(db, tenant_id, run.dataset_id)
        DatasetService.assert_dataset_writable(db, ds, account_id)

    stats = dict(run.stats or {})
    failed_urls = _extract_failed_urls(stats)
    # Keep it bounded (web_crawl max_pages <= 500).
    failed_urls = failed_urls[:500]
    if not failed_urls:
        raise HTTPException(status_code=400, detail="No failed URLs to retry")

    base_cfg = dict(run.config or {})
    connector_id = str(run.connector_id or "").strip()
    new_connector_id = "url_batch"
    new_cfg: dict[str, Any] = {"urls": failed_urls}

    if connector_id == "url_batch":
        new_cfg = dict(base_cfg)
        new_cfg["urls"] = failed_urls
    elif connector_id == "web_crawl":
        for k in ("filename", "user_agent", "auth", "parser_backend", "chunk_strategy", "pipeline", "access"):
            if k in base_cfg:
                new_cfg[k] = base_cfg.get(k)
    else:
        raise HTTPException(status_code=400, detail="Unsupported connector_id")

    new_run = ConnectorRun(
        tenant_id=tenant_id,
        dataset_id=run.dataset_id,
        connector_id=new_connector_id,
        requested_by=account_id,
        status="pending",
        config=new_cfg,
        stats={"retry_of": str(run.id), "retry_kind": "failed_only"},
    )
    db.add(new_run)
    db.commit()
    db.refresh(new_run)

    background_tasks.add_task(_execute_url_batch_run, run_id=new_run.id, tenant_id=tenant_id, requested_by=account_id)
    return _run_out(new_run)


@router.post("/runs/{run_id}/resume", response_model=ConnectorRunOut, status_code=201)
async def resume_connector_run(
    run_id: UUID,
    background_tasks: BackgroundTasks,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """Create a new connector run that resumes from where the previous run stopped (best-effort)."""
    if not bool(getattr(settings, "URL_INGEST_ENABLED", False)):
        raise HTTPException(status_code=400, detail="URL ingestion is disabled")

    DatasetService.ensure_member(db, tenant_id, account_id)

    run = db.query(ConnectorRun).filter(ConnectorRun.id == run_id, ConnectorRun.tenant_id == tenant_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Connector run not found")

    status = str(run.status or "").lower()
    if status not in {"cancelled", "failed"}:
        raise HTTPException(status_code=400, detail="Connector run is not resumable")

    if run.dataset_id:
        ds = DatasetService.get_dataset(db, tenant_id, run.dataset_id)
        DatasetService.assert_dataset_writable(db, ds, account_id)

    connector_id = str(run.connector_id or "").strip()
    if connector_id != "url_batch":
        raise HTTPException(status_code=400, detail="Resume is only supported for url_batch")

    stats = dict(run.stats or {})
    cursor_raw = stats.get("cursor", stats.get("processed_urls", 0))
    try:
        cursor = max(0, int(cursor_raw or 0))
    except Exception:
        cursor = 0

    base_cfg = dict(run.config or {})
    urls = base_cfg.get("urls") if isinstance(base_cfg.get("urls"), list) else []
    urls = [str(u or "").strip() for u in urls if str(u or "").strip()]
    remaining = urls[cursor:] if cursor < len(urls) else []
    if not remaining:
        raise HTTPException(status_code=400, detail="No remaining URLs to resume")

    new_cfg = dict(base_cfg)
    new_cfg["urls"] = remaining
    new_run = ConnectorRun(
        tenant_id=tenant_id,
        dataset_id=run.dataset_id,
        connector_id="url_batch",
        requested_by=account_id,
        status="pending",
        config=new_cfg,
        stats={"resume_of": str(run.id), "resume_cursor": int(cursor)},
    )
    db.add(new_run)
    db.commit()
    db.refresh(new_run)

    background_tasks.add_task(_execute_url_batch_run, run_id=new_run.id, tenant_id=tenant_id, requested_by=account_id)
    return _run_out(new_run)


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


@router.get("/configs", response_model=ConnectorConfigListResponse)
def list_connector_configs(
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=200),
    dataset_id: UUID | None = None,
    connector_id: str | None = None,
    enabled: bool | None = None,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """
    List saved connector configurations.

    Note: configs may contain secrets (even if encrypted); we enforce dataset write permission
    semantics similar to connector runs to avoid leaking URLs/auth details to readers.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)

    query = db.query(ConnectorConfig).filter(ConnectorConfig.tenant_id == tenant_id)
    if dataset_id is not None:
        ds = DatasetService.get_dataset(db, tenant_id, dataset_id)
        DatasetService.assert_dataset_writable(db, ds, account_id)
        query = query.filter(ConnectorConfig.dataset_id == dataset_id)
    if connector_id:
        query = query.filter(ConnectorConfig.connector_id == str(connector_id))
    if enabled is not None:
        query = query.filter(ConnectorConfig.enabled.is_(bool(enabled)))

    total = int(query.count())
    items = (
        query.order_by(ConnectorConfig.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    # If dataset_id isn't provided, filter to writable datasets only.
    if dataset_id is None:
        allowed: list[ConnectorConfig] = []
        for cfg in items:
            try:
                ds = DatasetService.get_dataset(db, tenant_id, cfg.dataset_id)
                DatasetService.assert_dataset_writable(db, ds, account_id)
            except HTTPException:
                continue
            allowed.append(cfg)
        items = allowed

    return {"total": total, "items": [_config_out(c) for c in items]}


@router.post("/configs", response_model=ConnectorConfigOut, status_code=201)
def create_connector_config(
    payload: ConnectorConfigCreateRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """Create a saved connector configuration."""
    DatasetService.ensure_member(db, tenant_id, account_id)
    ds = DatasetService.get_dataset(db, tenant_id, payload.dataset_id)
    DatasetService.assert_dataset_writable(db, ds, account_id)

    cfg_dict = encrypt_connector_config_secrets(dict(payload.config or {}))

    cfg = ConnectorConfig(
        tenant_id=tenant_id,
        dataset_id=payload.dataset_id,
        connector_id=str(payload.connector_id or "").strip(),
        name=str(payload.name or "").strip(),
        enabled=bool(payload.enabled),
        schedule_cron=(str(payload.schedule_cron).strip() if isinstance(payload.schedule_cron, str) and payload.schedule_cron.strip() else None),
        config=cfg_dict,
        state={},
    )
    db.add(cfg)
    db.commit()
    db.refresh(cfg)
    return _config_out(cfg)


@router.put("/configs/{config_id}", response_model=ConnectorConfigOut)
def update_connector_config(
    config_id: UUID,
    payload: ConnectorConfigUpdateRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """Update a saved connector configuration (best-effort)."""
    DatasetService.ensure_member(db, tenant_id, account_id)

    cfg = (
        db.query(ConnectorConfig)
        .filter(ConnectorConfig.id == config_id, ConnectorConfig.tenant_id == tenant_id)
        .first()
    )
    if not cfg:
        raise HTTPException(status_code=404, detail="Connector config not found")

    ds = DatasetService.get_dataset(db, tenant_id, cfg.dataset_id)
    DatasetService.assert_dataset_writable(db, ds, account_id)

    if payload.name is not None:
        cfg.name = str(payload.name or "").strip()  # type: ignore[assignment]
    if payload.enabled is not None:
        cfg.enabled = bool(payload.enabled)  # type: ignore[assignment]
    if payload.schedule_cron is not None:
        cfg.schedule_cron = (str(payload.schedule_cron).strip() if str(payload.schedule_cron or "").strip() else None)  # type: ignore[assignment]
    if payload.config is not None:
        cfg.config = encrypt_connector_config_secrets(dict(payload.config or {}))  # type: ignore[assignment]
    if payload.state is not None:
        cfg.state = dict(payload.state or {})  # type: ignore[assignment]

    db.commit()
    db.refresh(cfg)
    return _config_out(cfg)


@router.delete("/configs/{config_id}", status_code=204)
def delete_connector_config(
    config_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """Delete a saved connector configuration."""
    DatasetService.ensure_member(db, tenant_id, account_id)

    cfg = (
        db.query(ConnectorConfig)
        .filter(ConnectorConfig.id == config_id, ConnectorConfig.tenant_id == tenant_id)
        .first()
    )
    if not cfg:
        raise HTTPException(status_code=404, detail="Connector config not found")

    ds = DatasetService.get_dataset(db, tenant_id, cfg.dataset_id)
    DatasetService.assert_dataset_writable(db, ds, account_id)

    db.delete(cfg)
    db.commit()
    return Response(status_code=204)


@router.post("/configs/{config_id}/run", response_model=ConnectorRunOut, status_code=201)
async def run_connector_config(
    config_id: UUID,
    background_tasks: BackgroundTasks,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """Create a connector run from a saved connector configuration."""
    DatasetService.ensure_member(db, tenant_id, account_id)

    cfg = (
        db.query(ConnectorConfig)
        .filter(ConnectorConfig.id == config_id, ConnectorConfig.tenant_id == tenant_id)
        .first()
    )
    if not cfg:
        raise HTTPException(status_code=404, detail="Connector config not found")

    ds = DatasetService.get_dataset(db, tenant_id, cfg.dataset_id)
    DatasetService.assert_dataset_writable(db, ds, account_id)

    connector_id = str(cfg.connector_id or "").strip()
    run_cfg = dict(cfg.config or {})

    run = ConnectorRun(
        tenant_id=tenant_id,
        dataset_id=cfg.dataset_id,
        connector_id=connector_id,
        requested_by=account_id,
        status="pending",
        config=run_cfg,
        stats={"config_id": str(cfg.id)},
    )
    db.add(run)
    cfg.last_run_at = _now()  # type: ignore[assignment]
    cfg.last_error = None  # type: ignore[assignment]
    db.commit()
    db.refresh(run)

    # Execute asynchronously after response.
    if connector_id == "url_batch":
        background_tasks.add_task(_execute_url_batch_run, run_id=run.id, tenant_id=tenant_id, requested_by=account_id)
    elif connector_id == "web_crawl":
        background_tasks.add_task(_execute_web_crawl_run, run_id=run.id, tenant_id=tenant_id, requested_by=account_id)
    else:
        raise HTTPException(status_code=400, detail="Unsupported connector_id")

    return _run_out(run)


@router.post("/scheduled/tick")
async def scheduled_tick(
    background_tasks: BackgroundTasks,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """
    Evaluate saved connector schedules and enqueue due runs (best-effort).

    This endpoint is intentionally simple and deterministic; it is a "tick hook" for an external scheduler.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)

    now = _now()
    rows = (
        db.query(ConnectorConfig)
        .filter(
            ConnectorConfig.tenant_id == tenant_id,
            ConnectorConfig.enabled.is_(True),
            ConnectorConfig.schedule_cron.isnot(None),
        )
        .order_by(ConnectorConfig.created_at.asc())
        .limit(200)
        .all()
    )

    enqueued = 0
    skipped = 0
    for cfg in rows:
        schedule = str(cfg.schedule_cron or "").strip()
        if not schedule:
            skipped += 1
            continue
        if not _schedule_due(schedule=schedule, now=now, last_run_at=(cfg.last_run_at or None)):
            skipped += 1
            continue
        # Best-effort permission enforcement: skip datasets the caller can't write.
        try:
            ds = DatasetService.get_dataset(db, tenant_id, cfg.dataset_id)
            DatasetService.assert_dataset_writable(db, ds, account_id)
        except HTTPException:
            skipped += 1
            continue

        # Create run and enqueue execution.
        connector_id = str(cfg.connector_id or "").strip()
        run = ConnectorRun(
            tenant_id=tenant_id,
            dataset_id=cfg.dataset_id,
            connector_id=connector_id,
            requested_by=account_id,
            status="pending",
            config=dict(cfg.config or {}),
            stats={"config_id": str(cfg.id), "scheduled": True},
        )
        db.add(run)
        cfg.last_run_at = now  # type: ignore[assignment]
        cfg.last_error = None  # type: ignore[assignment]
        db.commit()
        db.refresh(run)

        if connector_id == "url_batch":
            background_tasks.add_task(_execute_url_batch_run, run_id=run.id, tenant_id=tenant_id, requested_by=account_id)
        elif connector_id == "web_crawl":
            background_tasks.add_task(_execute_web_crawl_run, run_id=run.id, tenant_id=tenant_id, requested_by=account_id)
        else:
            # Unknown connector: mark as failed (best-effort) and continue.
            run.status = "failed"
            run.error_message = "unsupported_connector_id"
            run.finished_at = now
            cfg.last_error = "unsupported_connector_id"  # type: ignore[assignment]
            db.commit()
        enqueued += 1

    return {"enqueued": int(enqueued), "skipped": int(skipped)}
