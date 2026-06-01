from __future__ import annotations

import asyncio
import contextlib
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session, selectinload

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.connector import (
    ConfluenceSpaceConnectorConfig,
    ConnectorRunCreateRequest,
    ConnectorRunListResponse,
    ConnectorRunOut,
    DriveFilesConnectorConfig,
    GitHubRepoConnectorConfig,
    JiraProjectConnectorConfig,
    MinioBucketConnectorConfig,
    MySQLCatalogConnectorConfig,
    SQLServerCatalogConnectorConfig,
    UrlBatchConnectorConfig,
    WebCrawlConnectorConfig,
)
from app.api.v1 import connectors as connectors_module
from app.core.database import get_db
from app.models.connector import ConnectorRun

router = APIRouter(responses=connectors_module._DEFAULT_HTTP_EXCEPTION_RESPONSES)


def _extract_failed_urls(stats: dict) -> list[str]:
    urls: list[str] = []
    raw_failed = stats.get("failed_urls")
    if isinstance(raw_failed, list):
        urls = [str(url or "").strip() for url in raw_failed if str(url or "").strip()]
    if not urls:
        raw_errors = stats.get("errors")
        if isinstance(raw_errors, list):
            urls = [str((error or {}).get("url") or "").strip() for error in raw_errors if isinstance(error, dict)]
            urls = [url for url in urls if url]
    seen: set[str] = set()
    out: list[str] = []
    for url in urls:
        if url in seen:
            continue
        seen.add(url)
        out.append(url)
    return out


def _get_connector_run_or_404(db: Session, *, run_id: UUID, tenant_id: UUID) -> ConnectorRun:
    run = db.query(ConnectorRun).filter(ConnectorRun.id == run_id, ConnectorRun.tenant_id == tenant_id).first()
    if not run:
        raise HTTPException(status_code=404, detail=connectors_module.CONNECTOR_RUN_NOT_FOUND_DETAIL)
    return run


def _assert_connector_run_dataset_writable(db: Session, *, run: ConnectorRun, tenant_id: UUID, account_id: str) -> None:
    if not run.dataset_id:
        return
    dataset = connectors_module.DatasetService.get_dataset(db, tenant_id, run.dataset_id)
    connectors_module.DatasetService.assert_dataset_writable(db, dataset, account_id)


def _build_retry_failed_run_config(
    *,
    connector_id: str,
    base_cfg: dict[str, Any],
    failed_urls: list[str],
) -> tuple[str, dict[str, Any]]:
    if connector_id == "url_batch":
        new_cfg = dict(base_cfg)
        new_cfg["urls"] = failed_urls
        return "url_batch", new_cfg

    if connector_id == "web_crawl":
        new_cfg: dict[str, Any] = {"urls": failed_urls}
        for key in ("filename", "user_agent", "auth", "parser_backend", "chunk_strategy", "pipeline", "access"):
            if key in base_cfg:
                new_cfg[key] = base_cfg.get(key)
        return "url_batch", new_cfg

    raise HTTPException(status_code=400, detail=connectors_module.UNSUPPORTED_CONNECTOR_ID_DETAIL)


async def _enqueue_connector_run_if_enabled(
    *,
    tenant_id: UUID,
    run_id: UUID,
    requested_by: str,
) -> str | None:
    if not bool(getattr(connectors_module.settings, "TASK_QUEUE_ENABLED", False)):
        return None

    job_id = f"connector:{tenant_id}:{run_id}"
    try:
        return await connectors_module.enqueue_connector_run(
            tenant_id=tenant_id,
            run_id=run_id,
            requested_by=requested_by,
            job_id=job_id,
        )
    except Exception:
        return None


def _persist_connector_run_task_id(db: Session, *, run: ConnectorRun, task_id: str) -> None:
    run.task_id = task_id
    db.commit()
    db.refresh(run)


def _schedule_connector_run_dispatch(
    *,
    background_tasks: BackgroundTasks,
    connector_id: str,
    run_id: UUID,
    tenant_id: UUID,
    requested_by: str,
) -> None:
    if connector_id == "url_batch":
        background_tasks.add_task(
            connectors_module._execute_url_batch_run,
            run_id=run_id,
            tenant_id=tenant_id,
            requested_by=requested_by,
        )
        return
    if connector_id == "web_crawl":
        background_tasks.add_task(
            connectors_module._execute_web_crawl_run,
            run_id=run_id,
            tenant_id=tenant_id,
            requested_by=requested_by,
        )
        return
    if connector_id == "github_repo":
        background_tasks.add_task(
            connectors_module._execute_github_repo_run,
            run_id=run_id,
            tenant_id=tenant_id,
            requested_by=requested_by,
        )
        return
    if connector_id == "drive_files":
        background_tasks.add_task(
            connectors_module._execute_drive_files_run,
            run_id=run_id,
            tenant_id=tenant_id,
            requested_by=requested_by,
        )
        return
    if connector_id == "minio_bucket":
        background_tasks.add_task(
            connectors_module._execute_minio_bucket_run,
            run_id=run_id,
            tenant_id=tenant_id,
            requested_by=requested_by,
        )
        return
    raise HTTPException(status_code=400, detail=connectors_module.UNSUPPORTED_CONNECTOR_ID_DETAIL)


def _connector_run_has_abortable_task(*, task_queue_enabled: bool, task_id: object) -> bool:
    return bool(task_queue_enabled and isinstance(task_id, str) and task_id)


def _load_arq_job_class():
    try:
        from arq.jobs import Job
    except ImportError:
        return None
    return Job


async def _get_queue_or_none():
    try:
        return await connectors_module.get_queue()
    except Exception:
        return None


async def _abort_connector_run_task_if_possible(run: ConnectorRun) -> None:
    task_id = getattr(run, "task_id", None)
    if not _connector_run_has_abortable_task(
        task_queue_enabled=bool(getattr(connectors_module.settings, "TASK_QUEUE_ENABLED", False)),
        task_id=task_id,
    ):
        return

    job_cls = connectors_module._load_arq_job_class()
    if job_cls is None:
        return

    queue = await connectors_module._get_queue_or_none()
    if queue is None:
        return

    queue_name = getattr(connectors_module.settings, "TASK_QUEUE_NAME", "mimirq")
    job = job_cls(str(task_id), queue, _queue_name=queue_name)
    with contextlib.suppress(TimeoutError, asyncio.TimeoutError):
        await job.abort(timeout=0.2)


@router.post("/runs", response_model=ConnectorRunOut, status_code=201, responses=connectors_module._DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def create_connector_run(
    payload: ConnectorRunCreateRequest,
    background_tasks: BackgroundTasks,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Create a connector run (currently supports url_batch).

    Requires dataset write permission.
    """
    connector_id = str(payload.connector_id or "").strip()
    url_connectors = {"url_batch", "web_crawl", "github_repo", "drive_files", "minio_bucket", "confluence_space", "jira_project"}
    db_catalog_connectors = {"mysql_catalog", "sqlserver_catalog"}

    if connector_id in url_connectors and not bool(getattr(connectors_module.settings, "URL_INGEST_ENABLED", False)):
        raise HTTPException(status_code=400, detail=connectors_module.URL_INGEST_DISABLED_DETAIL)
    if connector_id in db_catalog_connectors and not bool(getattr(connectors_module.settings, "DB_CATALOG_ENABLED", False)):
        raise HTTPException(status_code=400, detail="DB catalog ingestion is disabled")

    connectors_module.DatasetService.ensure_member(db, tenant_id, account_id)
    dataset = connectors_module._resolve_writable_dataset(db, tenant_id, account_id, payload.dataset_id)

    if connector_id == "url_batch":
        cfg = UrlBatchConnectorConfig.model_validate(payload.config or {})
        cfg_dict = connectors_module.encrypt_connector_config_secrets(cfg.model_dump(mode="json", exclude_none=True))
    elif connector_id == "web_crawl":
        cfg = WebCrawlConnectorConfig.model_validate(payload.config or {})
        cfg_dict = connectors_module.encrypt_connector_config_secrets(cfg.model_dump(mode="json", exclude_none=True))
    elif connector_id == "github_repo":
        cfg = GitHubRepoConnectorConfig.model_validate(payload.config or {})
        cfg_dict = connectors_module.encrypt_connector_config_secrets(cfg.model_dump(mode="json", exclude_none=True))
    elif connector_id == "drive_files":
        cfg = DriveFilesConnectorConfig.model_validate(payload.config or {})
        cfg_dict = connectors_module.encrypt_connector_config_secrets(cfg.model_dump(mode="json", exclude_none=True))
    elif connector_id == "minio_bucket":
        cfg = MinioBucketConnectorConfig.model_validate(payload.config or {})
        cfg_dict = connectors_module.encrypt_connector_config_secrets(cfg.model_dump(mode="json", exclude_none=True))
    elif connector_id == "confluence_space":
        cfg = ConfluenceSpaceConnectorConfig.model_validate(payload.config or {})
        cfg_dict = connectors_module.encrypt_connector_config_secrets(cfg.model_dump(mode="json", exclude_none=True))
    elif connector_id == "jira_project":
        cfg = JiraProjectConnectorConfig.model_validate(payload.config or {})
        cfg_dict = connectors_module.encrypt_connector_config_secrets(cfg.model_dump(mode="json", exclude_none=True))
    elif connector_id == "mysql_catalog":
        cfg = MySQLCatalogConnectorConfig.model_validate(payload.config or {})
        cfg_dict = connectors_module.encrypt_connector_config_secrets(cfg.model_dump(mode="json", exclude_none=True))
    elif connector_id == "sqlserver_catalog":
        cfg = SQLServerCatalogConnectorConfig.model_validate(payload.config or {})
        cfg_dict = connectors_module.encrypt_connector_config_secrets(cfg.model_dump(mode="json", exclude_none=True))
    else:
        raise HTTPException(status_code=400, detail=connectors_module.UNSUPPORTED_CONNECTOR_ID_DETAIL)

    group_ids_to_check: list[UUID] = []
    access = getattr(cfg, "access", None)
    group_ids_to_check.extend(list(getattr(access, "partial_group_list", None) or []))
    source_acl = getattr(cfg, "source_acl", None)
    for rule in getattr(source_acl, "group_mappings", None) or []:
        group_id = getattr(rule, "group_id", None)
        if group_id:
            group_ids_to_check.append(group_id)

    if group_ids_to_check:
        missing = connectors_module._unknown_tenant_groups(db, tenant_id=tenant_id, group_ids=group_ids_to_check)
        if missing:
            raise HTTPException(status_code=400, detail=f"Unknown tenant groups: {', '.join(missing[:20])}")

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

    task_id = await _enqueue_connector_run_if_enabled(
        tenant_id=tenant_id,
        run_id=run.id,
        requested_by=account_id,
    )
    if task_id:
        _persist_connector_run_task_id(db, run=run, task_id=task_id)
        return connectors_module._run_out(run)

    if connector_id == "url_batch":
        background_tasks.add_task(connectors_module._execute_url_batch_run, run_id=run.id, tenant_id=tenant_id, requested_by=account_id)
    elif connector_id == "web_crawl":
        background_tasks.add_task(connectors_module._execute_web_crawl_run, run_id=run.id, tenant_id=tenant_id, requested_by=account_id)
    elif connector_id == "github_repo":
        background_tasks.add_task(connectors_module._execute_github_repo_run, run_id=run.id, tenant_id=tenant_id, requested_by=account_id)
    elif connector_id == "drive_files":
        background_tasks.add_task(connectors_module._execute_drive_files_run, run_id=run.id, tenant_id=tenant_id, requested_by=account_id)
    elif connector_id == "minio_bucket":
        background_tasks.add_task(connectors_module._execute_minio_bucket_run, run_id=run.id, tenant_id=tenant_id, requested_by=account_id)
    elif connector_id == "confluence_space":
        background_tasks.add_task(connectors_module._execute_confluence_space_run, run_id=run.id, tenant_id=tenant_id, requested_by=account_id)
    elif connector_id == "jira_project":
        background_tasks.add_task(connectors_module._execute_jira_project_run, run_id=run.id, tenant_id=tenant_id, requested_by=account_id)
    elif connector_id in {"mysql_catalog", "sqlserver_catalog"}:
        background_tasks.add_task(connectors_module._execute_db_catalog_run, run_id=run.id, tenant_id=tenant_id, requested_by=account_id)
    else:
        raise HTTPException(status_code=400, detail=connectors_module.UNSUPPORTED_CONNECTOR_ID_DETAIL)

    return connectors_module._run_out(run)


@router.get("/runs", response_model=ConnectorRunListResponse, responses=connectors_module._DEFAULT_HTTP_EXCEPTION_RESPONSES)
def list_connector_runs(
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    dataset_id: UUID | None = None,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """List connector runs (requires dataset write permission for each returned run's dataset)."""
    connectors_module.DatasetService.ensure_member(db, tenant_id, account_id)

    query = db.query(ConnectorRun).filter(ConnectorRun.tenant_id == tenant_id)
    if dataset_id:
        dataset = connectors_module.DatasetService.get_dataset(db, tenant_id, dataset_id)
        connectors_module.DatasetService.assert_dataset_writable(db, dataset, account_id)
        query = query.filter(ConnectorRun.dataset_id == dataset_id)

    total = int(query.count())
    runs = (
        query.options(selectinload(ConnectorRun.documents))
        .order_by(ConnectorRun.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    if not dataset_id:
        allowed: list[ConnectorRun] = []
        for run in runs:
            if not run.dataset_id:
                continue
            try:
                dataset = connectors_module.DatasetService.get_dataset(db, tenant_id, run.dataset_id)
                connectors_module.DatasetService.assert_dataset_writable(db, dataset, account_id)
            except HTTPException:
                continue
            allowed.append(run)
        runs = allowed

    summaries = connectors_module._fetch_connector_run_acl_summaries(
        db,
        tenant_id=tenant_id,
        run_ids=[run.id for run in runs],
    )

    return {"total": total, "items": [connectors_module._run_out(run, acl_summary=summaries.get(run.id)) for run in runs]}


@router.get("/runs/{run_id}", response_model=ConnectorRunOut, responses=connectors_module._DEFAULT_HTTP_EXCEPTION_RESPONSES)
def get_connector_run(
    run_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Get connector run detail (requires dataset write permission)."""
    connectors_module.DatasetService.ensure_member(db, tenant_id, account_id)

    run = (
        db.query(ConnectorRun)
        .options(selectinload(ConnectorRun.documents))
        .filter(ConnectorRun.id == run_id, ConnectorRun.tenant_id == tenant_id)
        .first()
    )
    if not run:
        raise HTTPException(status_code=404, detail=connectors_module.CONNECTOR_RUN_NOT_FOUND_DETAIL)

    if run.dataset_id:
        dataset = connectors_module.DatasetService.get_dataset(db, tenant_id, run.dataset_id)
        connectors_module.DatasetService.assert_dataset_writable(db, dataset, account_id)

    summary = connectors_module._fetch_connector_run_acl_summaries(
        db,
        tenant_id=tenant_id,
        run_ids=[run.id],
    ).get(run.id)

    return connectors_module._run_out(run, acl_summary=summary)


@router.post("/runs/{run_id}/retry-failed", response_model=ConnectorRunOut, status_code=201, responses=connectors_module._DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def retry_failed_connector_run(
    run_id: UUID,
    background_tasks: BackgroundTasks,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Create a new connector run that retries only the failed URLs (best-effort)."""
    if not bool(getattr(connectors_module.settings, "URL_INGEST_ENABLED", False)):
        raise HTTPException(status_code=400, detail=connectors_module.URL_INGEST_DISABLED_DETAIL)

    connectors_module.DatasetService.ensure_member(db, tenant_id, account_id)

    run = _get_connector_run_or_404(db, run_id=run_id, tenant_id=tenant_id)

    status = str(run.status or "").lower()
    if status in {"pending", "running"}:
        raise HTTPException(status_code=400, detail="Connector run is still active")

    _assert_connector_run_dataset_writable(db, run=run, tenant_id=tenant_id, account_id=account_id)

    stats = dict(run.stats or {})
    failed_urls = _extract_failed_urls(stats)[:500]
    if not failed_urls:
        raise HTTPException(status_code=400, detail="No failed URLs to retry")

    base_cfg = dict(run.config or {})
    connector_id = str(run.connector_id or "").strip()
    new_connector_id, new_cfg = _build_retry_failed_run_config(
        connector_id=connector_id,
        base_cfg=base_cfg,
        failed_urls=failed_urls,
    )

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

    task_id = await _enqueue_connector_run_if_enabled(
        tenant_id=tenant_id,
        run_id=new_run.id,
        requested_by=account_id,
    )
    if task_id:
        _persist_connector_run_task_id(db, run=new_run, task_id=task_id)
        return connectors_module._run_out(new_run)

    _schedule_connector_run_dispatch(
        background_tasks=background_tasks,
        connector_id=new_connector_id,
        run_id=new_run.id,
        tenant_id=tenant_id,
        requested_by=account_id,
    )
    return connectors_module._run_out(new_run)


@router.post("/runs/{run_id}/resume", response_model=ConnectorRunOut, status_code=201, responses=connectors_module._DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def resume_connector_run(
    run_id: UUID,
    background_tasks: BackgroundTasks,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Create a new connector run that resumes from where the previous run stopped (best-effort)."""
    if not bool(getattr(connectors_module.settings, "URL_INGEST_ENABLED", False)):
        raise HTTPException(status_code=400, detail=connectors_module.URL_INGEST_DISABLED_DETAIL)

    connectors_module.DatasetService.ensure_member(db, tenant_id, account_id)

    run = _get_connector_run_or_404(db, run_id=run_id, tenant_id=tenant_id)

    status = str(run.status or "").lower()
    if status not in {"cancelled", "failed"}:
        raise HTTPException(status_code=400, detail="Connector run is not resumable")

    _assert_connector_run_dataset_writable(db, run=run, tenant_id=tenant_id, account_id=account_id)

    connector_id = str(run.connector_id or "").strip()
    connector_definition = connectors_module.get_connector_definition(connector_id)
    if connector_definition is None or not connector_definition.supports_resume:
        raise HTTPException(status_code=400, detail=f"Resume is not supported for {connector_id or 'this connector'}")

    base_cfg = dict(run.config or {})
    stats = dict(run.stats or {})
    new_cfg = dict(base_cfg)
    resume_stats: dict[str, Any] = {"resume_of": str(run.id)}

    if connector_id == "url_batch":
        cursor_raw = stats.get("cursor", stats.get("processed_urls", 0))
        try:
            cursor = max(0, int(cursor_raw or 0))
        except Exception:
            cursor = 0

        urls = base_cfg.get("urls") if isinstance(base_cfg.get("urls"), list) else []
        urls = [str(url or "").strip() for url in urls if str(url or "").strip()]
        remaining = urls[cursor:] if cursor < len(urls) else []
        if not remaining:
            raise HTTPException(status_code=400, detail="No remaining URLs to resume")
        new_cfg["urls"] = remaining
        resume_stats["resume_cursor"] = int(cursor)
    else:
        existing_state = base_cfg.get("_state") if isinstance(base_cfg.get("_state"), dict) else {}
        resume_state = connectors_module.build_persisted_state(
            connector_id=connector_id,
            existing_state=dict(existing_state or {}),
            stats=stats,
            run_id=run.id,
        )
        cursor = connectors_module.get_resume_cursor(resume_state)
        total_key = next((key for key in connector_definition.state_keys if key != "cursor"), None)
        has_incremental_manifest = bool(connectors_module.normalize_source_manifest(resume_state.get("source_manifest")))
        if total_key and not has_incremental_manifest:
            try:
                total_items = max(0, int(stats.get(total_key) or 0))
            except Exception:
                total_items = 0
            if total_items > 0 and cursor >= total_items:
                raise HTTPException(status_code=400, detail="No remaining items to resume")
        if not resume_state:
            raise HTTPException(status_code=400, detail="No saved resume state found")
        new_cfg["_state"] = resume_state
        resume_stats["resume_cursor"] = int(cursor)

    new_run = ConnectorRun(
        tenant_id=tenant_id,
        dataset_id=run.dataset_id,
        connector_id=connector_id,
        requested_by=account_id,
        status="pending",
        config=new_cfg,
        stats=resume_stats,
    )
    db.add(new_run)
    db.commit()
    db.refresh(new_run)

    task_id = await _enqueue_connector_run_if_enabled(
        tenant_id=tenant_id,
        run_id=new_run.id,
        requested_by=account_id,
    )
    if task_id:
        _persist_connector_run_task_id(db, run=new_run, task_id=task_id)
        return connectors_module._run_out(new_run)

    _schedule_connector_run_dispatch(
        background_tasks=background_tasks,
        connector_id=connector_id,
        run_id=new_run.id,
        tenant_id=tenant_id,
        requested_by=account_id,
    )
    return connectors_module._run_out(new_run)


@router.post("/runs/{run_id}/cancel", response_model=ConnectorRunOut, responses=connectors_module._DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def cancel_connector_run(
    run_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Cancel a running connector run (best-effort)."""
    connectors_module.DatasetService.ensure_member(db, tenant_id, account_id)

    run = _get_connector_run_or_404(db, run_id=run_id, tenant_id=tenant_id)
    _assert_connector_run_dataset_writable(db, run=run, tenant_id=tenant_id, account_id=account_id)

    status = str(run.status or "").lower()
    if status in {"completed", "failed"}:
        return connectors_module._run_out(run)

    run.status = "cancelled"
    run.finished_at = connectors_module._now()
    db.commit()
    db.refresh(run)

    await _abort_connector_run_task_if_possible(run)
    return connectors_module._run_out(run)
