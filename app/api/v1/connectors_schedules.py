from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.v1 import connectors as connectors_module
from app.core.database import get_db
from app.models.connector import ConnectorRun
from app.models.connector_config import ConnectorConfig

router = APIRouter(responses=connectors_module._DEFAULT_HTTP_EXCEPTION_RESPONSES)
_URL_CONNECTORS = {
    "url_batch",
    "web_crawl",
    "github_repo",
    "drive_files",
    "minio_bucket",
    "confluence_space",
    "jira_project",
}
_DB_CATALOG_CONNECTORS = {"mysql_catalog", "sqlserver_catalog"}


@dataclass(frozen=True)
class _ScheduledTickContext:
    background_tasks: BackgroundTasks
    db: Session
    tenant_id: UUID
    account_id: str
    now: datetime


def _scheduled_connector_configs(db: Session, tenant_id: UUID) -> list[ConnectorConfig]:
    return (
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


def _is_scheduled_config_due(cfg: ConnectorConfig, *, now: datetime) -> bool:
    schedule = str(cfg.schedule_cron or "").strip()
    if not schedule:
        return False
    return connectors_module._schedule_due(schedule=schedule, now=now, last_run_at=(cfg.last_run_at or None))


def _config_dataset_is_writable(ctx: _ScheduledTickContext, cfg: ConnectorConfig) -> bool:
    try:
        dataset = connectors_module.DatasetService.get_dataset(ctx.db, ctx.tenant_id, cfg.dataset_id)
        connectors_module.DatasetService.assert_dataset_writable(ctx.db, dataset, ctx.account_id)
    except HTTPException:
        return False
    return True


def _scheduled_run_config(cfg: ConnectorConfig, connector_id: str) -> dict:
    run_cfg = dict(cfg.config or {})
    connector_definition = connectors_module.get_connector_definition(connector_id)
    if connector_definition is not None and connector_definition.supports_incremental:
        run_cfg["_state"] = dict(cfg.state or {})
    return run_cfg


def _create_scheduled_run(ctx: _ScheduledTickContext, cfg: ConnectorConfig, connector_id: str) -> ConnectorRun:
    run = ConnectorRun(
        tenant_id=ctx.tenant_id,
        dataset_id=cfg.dataset_id,
        connector_id=connector_id,
        requested_by=ctx.account_id,
        status="pending",
        config=_scheduled_run_config(cfg, connector_id),
        stats={"config_id": str(cfg.id), "scheduled": True},
    )
    ctx.db.add(run)
    cfg.last_run_at = ctx.now  # type: ignore[assignment]
    cfg.last_error = None  # type: ignore[assignment]
    ctx.db.commit()
    ctx.db.refresh(run)
    return run


def _disabled_connector_error(connector_id: str) -> str | None:
    if connector_id in _URL_CONNECTORS and not bool(getattr(connectors_module.settings, "URL_INGEST_ENABLED", False)):
        return "url_ingest_disabled"
    if connector_id in _DB_CATALOG_CONNECTORS and not bool(getattr(connectors_module.settings, "DB_CATALOG_ENABLED", False)):
        return "db_catalog_disabled"
    return None


def _mark_scheduled_run_failed(ctx: _ScheduledTickContext, cfg: ConnectorConfig, run: ConnectorRun, error: str) -> None:
    run.status = "failed"
    run.error_message = error
    run.finished_at = ctx.now
    cfg.last_error = error  # type: ignore[assignment]
    ctx.db.commit()


def _enqueue_scheduled_connector(ctx: _ScheduledTickContext, connector_id: str, run: ConnectorRun) -> bool:
    task_map = {
        "url_batch": connectors_module._execute_url_batch_run,
        "web_crawl": connectors_module._execute_web_crawl_run,
        "github_repo": connectors_module._execute_github_repo_run,
        "drive_files": connectors_module._execute_drive_files_run,
        "minio_bucket": connectors_module._execute_minio_bucket_run,
        "confluence_space": connectors_module._execute_confluence_space_run,
        "jira_project": connectors_module._execute_jira_project_run,
        "mysql_catalog": connectors_module._execute_db_catalog_run,
        "sqlserver_catalog": connectors_module._execute_db_catalog_run,
    }
    task = task_map.get(connector_id)
    if task is None:
        return False
    ctx.background_tasks.add_task(task, run_id=run.id, tenant_id=ctx.tenant_id, requested_by=ctx.account_id)
    return True


def _process_scheduled_config(ctx: _ScheduledTickContext, cfg: ConnectorConfig) -> str:
    if not _is_scheduled_config_due(cfg, now=ctx.now):
        return "skipped"
    if not _config_dataset_is_writable(ctx, cfg):
        return "skipped"

    connector_id = str(cfg.connector_id or "").strip()
    run = _create_scheduled_run(ctx, cfg, connector_id)
    if disabled_error := _disabled_connector_error(connector_id):
        _mark_scheduled_run_failed(ctx, cfg, run, disabled_error)
        return "enqueued"
    if not _enqueue_scheduled_connector(ctx, connector_id, run):
        _mark_scheduled_run_failed(ctx, cfg, run, "unsupported_connector_id")
    return "enqueued"


@router.post("/scheduled/tick", responses=connectors_module._DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def scheduled_tick(
    background_tasks: BackgroundTasks,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Evaluate saved connector schedules and enqueue due runs (best-effort).

    This endpoint is intentionally simple and deterministic; it is a "tick hook" for an external scheduler.
    """
    connectors_module.DatasetService.ensure_member(db, tenant_id, account_id)

    now = connectors_module._now()
    rows = _scheduled_connector_configs(db, tenant_id)
    ctx = _ScheduledTickContext(
        background_tasks=background_tasks,
        db=db,
        tenant_id=tenant_id,
        account_id=account_id,
        now=now,
    )

    enqueued = 0
    skipped = 0
    for cfg in rows:
        result = _process_scheduled_config(ctx, cfg)
        if result == "enqueued":
            enqueued += 1
        else:
            skipped += 1

    return {"enqueued": int(enqueued), "skipped": int(skipped)}
