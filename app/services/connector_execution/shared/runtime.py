"""Small shared runtime operations used by connector workers."""

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.connector import ConnectorRun
from app.models.connector_config import ConnectorConfig
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
