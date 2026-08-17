from dataclasses import dataclass
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.v1 import connectors as connectors_module
from app.api.v1.connectors_runs import (
    CONNECTOR_QUEUE_HANDOFF_FAILED_ERROR,
    _create_pending_connector_run,
    _enqueue_or_schedule_connector_run,
)
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


def _claim_scheduled_config_window(ctx: _ScheduledTickContext, cfg: ConnectorConfig) -> bool:
    where = [
        ConnectorConfig.id == cfg.id,
        ConnectorConfig.tenant_id == ctx.tenant_id,
        ConnectorConfig.enabled.is_(True),
    ]
    if cfg.last_run_at is None:
        where.append(ConnectorConfig.last_run_at.is_(None))
    else:
        where.append(ConnectorConfig.last_run_at == cfg.last_run_at)

    result = ctx.db.execute(update(ConnectorConfig).where(*where).values(last_run_at=ctx.now, last_error=None))
    return bool(getattr(result, "rowcount", 0))


def _create_scheduled_run(ctx: _ScheduledTickContext, cfg: ConnectorConfig, connector_id: str) -> ConnectorRun:
    run = _create_pending_connector_run(
        ctx.db,
        values={
            "tenant_id": ctx.tenant_id,
            "dataset_id": cfg.dataset_id,
            "connector_id": connector_id,
            "requested_by": ctx.account_id,
            "config": _scheduled_run_config(cfg, connector_id),
            "stats": {"config_id": str(cfg.id), "scheduled": True},
        },
    )
    return run


def _disabled_connector_error(connector_id: str) -> str | None:
    if connector_id in _URL_CONNECTORS and not bool(getattr(connectors_module.settings, "URL_INGEST_ENABLED", False)):
        return "url_ingest_disabled"
    if connector_id in _DB_CATALOG_CONNECTORS and not bool(
        getattr(connectors_module.settings, "DB_CATALOG_ENABLED", False)
    ):
        return "db_catalog_disabled"
    return None


def _mark_scheduled_run_failed(ctx: _ScheduledTickContext, cfg: ConnectorConfig, run: ConnectorRun, error: str) -> None:
    run.status = "failed"
    run.error_message = error
    run.finished_at = ctx.now
    cfg.last_run_at = ctx.now  # type: ignore[assignment]
    cfg.last_error = error  # type: ignore[assignment]
    ctx.db.commit()


def _release_scheduled_config_window(
    ctx: _ScheduledTickContext,
    cfg: ConnectorConfig,
    *,
    previous_last_run_at: datetime | None,
    error: str,
) -> None:
    result = ctx.db.execute(
        update(ConnectorConfig)
        .where(
            ConnectorConfig.id == cfg.id,
            ConnectorConfig.tenant_id == ctx.tenant_id,
            ConnectorConfig.last_run_at == ctx.now,
        )
        .values(last_run_at=previous_last_run_at, last_error=error)
    )
    if getattr(result, "rowcount", 0):
        cfg.last_run_at = previous_last_run_at  # type: ignore[assignment]
        cfg.last_error = error  # type: ignore[assignment]
    ctx.db.commit()


async def _process_scheduled_config(ctx: _ScheduledTickContext, cfg: ConnectorConfig) -> str:
    if not _is_scheduled_config_due(cfg, now=ctx.now):
        return "skipped"
    if not _config_dataset_is_writable(ctx, cfg):
        return "skipped"
    previous_last_run_at = cfg.last_run_at
    if not _claim_scheduled_config_window(ctx, cfg):
        return "skipped"

    connector_id = str(cfg.connector_id or "").strip()
    run = _create_scheduled_run(ctx, cfg, connector_id)
    if disabled_error := _disabled_connector_error(connector_id):
        _mark_scheduled_run_failed(ctx, cfg, run, disabled_error)
        return "enqueued"
    try:
        await _enqueue_or_schedule_connector_run(
            ctx.db,
            background_tasks=ctx.background_tasks,
            run=run,
            tenant_id=ctx.tenant_id,
            requested_by=ctx.account_id,
        )
    except HTTPException as exc:
        if exc.status_code == 503:
            _release_scheduled_config_window(
                ctx,
                cfg,
                previous_last_run_at=previous_last_run_at,
                error=CONNECTOR_QUEUE_HANDOFF_FAILED_ERROR,
            )
            raise
        if exc.status_code == 400:
            _mark_scheduled_run_failed(ctx, cfg, run, "unsupported_connector_id")
        else:
            raise
    else:
        cfg.last_run_at = ctx.now  # type: ignore[assignment]
        cfg.last_error = None  # type: ignore[assignment]
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
        result = await _process_scheduled_config(ctx, cfg)
        if result == "enqueued":
            enqueued += 1
        else:
            skipped += 1

    return {"enqueued": int(enqueued), "skipped": int(skipped)}
