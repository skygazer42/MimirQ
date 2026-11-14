from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.api.schemas.sources import ConnectorRunOut
from app.core.config import settings
from app.models.connector import ConnectorRun
from app.models.connector_config import ConnectorConfig
from app.services import dataset_service
from app.services.connector_config_operations import build_saved_connector_run_config
from app.services.connector_execution.shared.runtime import _now
from app.services.connector_run_operations import (
    _DB_CATALOG_CONNECTOR_IDS,
    _DB_CONNECTOR_PERMISSION_DETAIL,
    _URL_INGEST_CONNECTOR_IDS,
    CONNECTOR_QUEUE_HANDOFF_FAILED_ERROR,
    _create_pending_connector_run,
    _get_connector_run_or_404,
    _run_out,
    enqueue_or_schedule_run,
)
from app.services.managed_handoff import prepare_managed_handoff
from app.services.rag_runtime_limiter import run_blocking_call_with_managed_session
from app.services.rbac_service import TenantPermissions, ensure_tenant_permission

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
    schedule = cfg.schedule_cron
    if schedule is not None:
        schedule = schedule.strip()
    if not schedule:
        return False
    return _schedule_due(schedule=schedule, now=now, last_run_at=cfg.last_run_at)


def _config_dataset_is_writable(ctx: _ScheduledTickContext, cfg: ConnectorConfig) -> bool:
    try:
        dataset = dataset_service.get_dataset(ctx.db, ctx.tenant_id, cfg.dataset_id)
        dataset_service.assert_dataset_writable(ctx.db, dataset, ctx.account_id)
    except HTTPException:
        return False
    return True


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
    return bool(result.rowcount)


def _create_scheduled_run(ctx: _ScheduledTickContext, cfg: ConnectorConfig, connector_id: str) -> ConnectorRun:
    run = _create_pending_connector_run(
        ctx.db,
        values={
            "tenant_id": ctx.tenant_id,
            "dataset_id": cfg.dataset_id,
            "connector_id": connector_id,
            "requested_by": ctx.account_id,
            "config": build_saved_connector_run_config(cfg),
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
    if result.rowcount:
        cfg.last_run_at = previous_last_run_at  # type: ignore[assignment]
        cfg.last_error = error  # type: ignore[assignment]
    ctx.db.commit()


def _prepare_scheduled_config(
    db: Session, *, config_id: UUID, tenant_id: UUID, account_id: str, now: datetime, background_tasks: BackgroundTasks
) -> tuple[str, ConnectorRunOut | None, datetime | None]:
    cfg = (
        db.query(ConnectorConfig)
        .filter(ConnectorConfig.id == config_id, ConnectorConfig.tenant_id == tenant_id)
        .first()
    )
    if cfg is None:
        return "skipped", None, None
    ctx = _ScheduledTickContext(
        background_tasks=background_tasks, db=db, tenant_id=tenant_id, account_id=account_id, now=now
    )
    if not _is_scheduled_config_due(cfg, now=now) or not _config_dataset_is_writable(ctx, cfg):
        return "skipped", None, None
    connector_id = cfg.connector_id.strip()
    if connector_id in _DB_CATALOG_CONNECTORS:
        try:
            ensure_tenant_permission(
                db, tenant_id, account_id, TenantPermissions.SETTINGS_WRITE, detail=_DB_CONNECTOR_PERMISSION_DETAIL
            )
        except HTTPException as exc:
            if exc.status_code != 403:
                raise
            return "skipped", None, None
    previous = cfg.last_run_at
    if not _claim_scheduled_config_window(ctx, cfg):
        return "skipped", None, None
    run = _create_scheduled_run(ctx, cfg, connector_id)
    if error := _disabled_connector_error(connector_id):
        _mark_scheduled_run_failed(ctx, cfg, run, error)
        return "enqueued", None, previous
    return "enqueued", _run_out(run), previous


def _recover_scheduled_config(
    db: Session,
    *,
    config_id: UUID,
    run_id: UUID,
    tenant_id: UUID,
    account_id: str,
    now: datetime,
    background_tasks: BackgroundTasks,
    previous: datetime | None,
    unavailable: bool,
    error: str,
) -> None:
    cfg = (
        db.query(ConnectorConfig)
        .filter(ConnectorConfig.id == config_id, ConnectorConfig.tenant_id == tenant_id)
        .first()
    )
    if cfg is None:
        raise HTTPException(status_code=404, detail="Connector config not found")
    ctx = _ScheduledTickContext(
        background_tasks=background_tasks, db=db, tenant_id=tenant_id, account_id=account_id, now=now
    )
    if unavailable:
        _release_scheduled_config_window(ctx, cfg, previous_last_run_at=previous, error=error)
    else:
        run = _get_connector_run_or_404(db, run_id=run_id, tenant_id=tenant_id)
        _mark_scheduled_run_failed(ctx, cfg, run, error)


async def tick_schedules(
    *, background_tasks: BackgroundTasks, db: Session, tenant_id: UUID, account_id: str
) -> dict[str, int]:
    def load_config_ids(worker_db: Session) -> list[UUID]:
        dataset_service.ensure_member(worker_db, tenant_id, account_id)
        return [cfg.id for cfg in _scheduled_connector_configs(worker_db, tenant_id)]

    config_ids = await run_blocking_call_with_managed_session(load_config_ids, request_db=None)
    now = _now()
    enqueued = 0
    skipped = 0
    for config_id in config_ids:

        def recover_cancelled(
            worker_db: Session, prepared: tuple[str, ConnectorRunOut | None, datetime | None]
        ) -> None:
            _status, prepared_run, previous = prepared
            if prepared_run is None:
                return
            run = _get_connector_run_or_404(worker_db, run_id=prepared_run.id, tenant_id=tenant_id)
            run.status = "failed"
            run.error_message = "connector_request_cancelled_before_handoff"
            run.finished_at = now
            _recover_scheduled_config(
                worker_db,
                config_id=config_id,
                run_id=run.id,
                tenant_id=tenant_id,
                account_id=account_id,
                now=now,
                background_tasks=background_tasks,
                previous=previous,
                unavailable=True,
                error="connector_request_cancelled_before_handoff",
            )

        status, run, previous = await prepare_managed_handoff(
            lambda worker_db: _prepare_scheduled_config(
                worker_db,
                config_id=config_id,
                tenant_id=tenant_id,
                account_id=account_id,
                now=now,
                background_tasks=background_tasks,
            ),
            recover_cancelled=recover_cancelled,
        )
        if status == "skipped":
            skipped += 1
            continue
        if run is not None:
            try:
                await enqueue_or_schedule_run(
                    db, background_tasks=background_tasks, run=run, tenant_id=tenant_id, requested_by=account_id
                )
            except HTTPException as exc:
                if exc.status_code not in {400, 503}:
                    raise
                unavailable = exc.status_code == 503
                await run_blocking_call_with_managed_session(
                    lambda worker_db: _recover_scheduled_config(
                        worker_db,
                        config_id=config_id,
                        run_id=run.id,
                        tenant_id=tenant_id,
                        account_id=account_id,
                        now=now,
                        background_tasks=background_tasks,
                        previous=previous,
                        unavailable=unavailable,
                        error=CONNECTOR_QUEUE_HANDOFF_FAILED_ERROR if unavailable else "unsupported_connector_id",
                    ),
                    request_db=None,
                )
                if unavailable:
                    raise
        enqueued += 1
    return {"enqueued": enqueued, "skipped": skipped}
