"""Small shared runtime operations used by connector workers."""

import contextlib
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session, selectinload

from app.models.connector import ConnectorRun
from app.models.connector_config import ConnectorConfig
from app.services.connector_execution.shared.common import _finalize_connector_stats
from app.services.connector_sync_state import build_saved_state_snapshot


def _now() -> datetime:
    return datetime.now(UTC)


def _sync_connector_config_from_run(db: Session, *, run: ConnectorRun) -> None:
    stats = dict(run.stats or {})
    raw_config_id = stats.get("config_id")
    config_id_text = str(raw_config_id or "").strip() if isinstance(raw_config_id, (str, UUID)) else ""
    if not config_id_text:
        return
    try:
        config_id = UUID(config_id_text)
    except ValueError:
        return

    config = (
        db.query(ConnectorConfig)
        .filter(ConnectorConfig.id == config_id, ConnectorConfig.tenant_id == run.tenant_id)
        .first()
    )
    if config is None:
        return

    status = str(run.status or "").lower()
    config.last_error = None if status == "completed" else (str(run.error_message or status)[:200] or status)
    config.last_run_at = run.started_at or run.finished_at or _now()
    config.state = build_saved_state_snapshot(
        connector_id=str(run.connector_id or "").strip(),
        existing_state=dict(config.state or {}),
        stats=stats,
        run_id=run.id,
        run_status=status,
        recorded_at=run.finished_at or run.started_at or _now(),
    )


def get_active_connector_run(db: Session, *, run_id: UUID, tenant_id: UUID) -> ConnectorRun | None:
    run = (
        db.query(ConnectorRun)
        .options(selectinload(ConnectorRun.documents))
        .filter(ConnectorRun.id == run_id, ConnectorRun.tenant_id == tenant_id)
        .first()
    )
    if not run:
        return None
    if str(run.status or "").lower() in {"cancelled", "completed", "failed"}:
        return None
    return run


def mark_connector_run_running(db: Session, *, run: ConnectorRun) -> None:
    run.status = "running"
    run.started_at = _now()
    run.error_message = None
    run.stats = dict(run.stats or {})
    db.commit()
    db.refresh(run)


def finalize_cancelled_connector_run(db: Session, *, run: ConnectorRun) -> None:
    if run.finished_at is None:
        run.finished_at = _now()
    run.stats = _finalize_connector_stats(dict(run.stats or {}))
    db.commit()
    with contextlib.suppress(Exception):
        _sync_connector_config_from_run(db, run=run)


def mark_connector_run_failed(db: Session, *, run_id: UUID, tenant_id: UUID, exc: Exception) -> None:
    with contextlib.suppress(Exception):
        run = db.query(ConnectorRun).filter(ConnectorRun.id == run_id, ConnectorRun.tenant_id == tenant_id).first()
        if run is not None:
            run.status = "failed"
            run.finished_at = _now()
            run.error_message = str(exc)[:200]
            db.commit()
            with contextlib.suppress(Exception):
                _sync_connector_config_from_run(db, run=run)
