from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.connector import ConnectorRun
from app.models.connector_config import ConnectorConfig
from app.services import dataset_service
from app.services.connector_execution.shared.runtime import _now
from app.services.connector_registry import get_connector_definition
from app.services.connector_run_operations import (
    _DB_CATALOG_CONNECTOR_IDS,
    _URL_INGEST_CONNECTOR_IDS,
    CONNECTOR_QUEUE_HANDOFF_FAILED_ERROR,
    _create_pending_connector_run,
    enqueue_or_schedule_run,
)

_URL_CONNECTORS = _URL_INGEST_CONNECTOR_IDS
_DB_CATALOG_CONNECTORS = _DB_CATALOG_CONNECTOR_IDS


def _schedule_elapsed_seconds(*, now: datetime, last_run_at: datetime | None) -> float:
    if last_run_at is None:
        return 10**18
    return (now - last_run_at).total_seconds()


def _schedule_positive_int(raw: str) -> int | None:
    try:
        return max(1, int(raw))
    except ValueError:
        return None


def _schedule_interval_from_parts(minute: str, hour: str, day: str, month: str, dow: str) -> int | None:
    step_patterns = (
        (minute.startswith("*/") and hour == "*" and day == "*" and month == "*" and dow == "*", minute[2:], 60),
        (minute == "0" and hour.startswith("*/") and day == "*" and month == "*" and dow == "*", hour[2:], 3600),
        (minute == "0" and hour == "0" and day.startswith("*/") and month == "*" and dow == "*", day[2:], 86400),
    )
    for matched, raw_value, multiplier in step_patterns:
        if matched:
            value = _schedule_positive_int(raw_value)
            return None if value is None else multiplier * value
    return None


def _schedule_interval_seconds(schedule: str) -> int | None:
    raw = schedule.strip().lower()
    if not raw:
        return None
    fixed_intervals = {"@hourly": 3600, "@daily": 86400, "@weekly": 604800, "@monthly": 2592000}
    if raw in fixed_intervals:
        return fixed_intervals[raw]
    parts = raw.split()
    if len(parts) != 5:
        return None
    return _schedule_interval_from_parts(*parts)


def _schedule_due(*, schedule: str, now: datetime, last_run_at: datetime | None) -> bool:
    interval_seconds = _schedule_interval_seconds(schedule)
    return (
        interval_seconds is not None
        and _schedule_elapsed_seconds(
            now=now,
            last_run_at=last_run_at,
        )
        >= interval_seconds
    )


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
    return _schedule_due(schedule=schedule, now=now, last_run_at=(cfg.last_run_at or None))


def _config_dataset_is_writable(ctx: _ScheduledTickContext, cfg: ConnectorConfig) -> bool:
    try:
        dataset = dataset_service.get_dataset(ctx.db, ctx.tenant_id, cfg.dataset_id)
        dataset_service.assert_dataset_writable(ctx.db, dataset, ctx.account_id)
    except HTTPException:
        return False
    return True


def _scheduled_run_config(cfg: ConnectorConfig, connector_id: str) -> dict:
    run_cfg = dict(cfg.config or {})
    connector_definition = get_connector_definition(connector_id)
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
    if connector_id in _URL_CONNECTORS and not settings.URL_INGEST_ENABLED:
        return "url_ingest_disabled"
    if connector_id in _DB_CATALOG_CONNECTORS and not settings.DB_CATALOG_ENABLED:
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
        await enqueue_or_schedule_run(
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


async def tick_schedules(
    *,
    background_tasks: BackgroundTasks,
    db: Session,
    tenant_id: UUID,
    account_id: str,
) -> dict[str, int]:
    """
    Evaluate saved connector schedules and enqueue due runs (best-effort).

    This endpoint is intentionally simple and deterministic; it is a "tick hook" for an external scheduler.
    """
    dataset_service.ensure_member(db, tenant_id, account_id)

    now = _now()
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
