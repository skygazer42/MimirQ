
import contextlib
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import and_, func
from sqlalchemy.orm import Session

from app.api.schemas.connector import ConnectorConfigOut, ConnectorRunOut
from app.core.secrets import redact_secrets
from app.models.connector import ConnectorRun, ConnectorRunDocument
from app.models.connector_config import ConnectorConfig
from app.models.document import Document as DBDocument
from app.models.document import DocumentPermission
from app.models.group_permissions import DocumentGroupPermission
from app.models.tenant_group import TenantGroup
from app.services.connector_sync_state import build_saved_state_snapshot
from app.services.security_redaction import redact_connection_info

_leader_module = None


def _now() -> datetime:
    leader = globals().get("_leader_module")
    if leader is not None and hasattr(leader, "_now"):
        return leader._now()
    from datetime import UTC

    return datetime.now(UTC)


def _unknown_tenant_groups(
    db: Session,
    *,
    tenant_id: UUID,
    group_ids: list[UUID],
) -> list[str]:
    ids: list[UUID] = []
    seen: set[UUID] = set()
    for gid in group_ids or []:
        if gid in seen:
            continue
        seen.add(gid)
        ids.append(gid)
        if len(ids) >= 200:
            break

    if not ids:
        return []

    rows = (
        db.query(TenantGroup.id)
        .filter(TenantGroup.tenant_id == tenant_id, TenantGroup.id.in_(ids))
        .all()
    )
    found = {row[0] for row in rows if row and row[0]}
    return [str(gid) for gid in ids if gid not in found]


def _normalize_doc_access_mode(value: object) -> str:
    mode = str(value or "").strip().lower()
    if not mode or mode == "inherit":
        return "inherit"
    return mode


def _fetch_connector_run_acl_summaries(
    db: Session,
    *,
    tenant_id: UUID,
    run_ids: list[UUID],
) -> dict[UUID, dict[str, Any]]:
    if not run_ids:
        return {}

    seen: set[UUID] = set()
    normalized_run_ids: list[UUID] = []
    for rid in run_ids:
        if rid in seen:
            continue
        seen.add(rid)
        normalized_run_ids.append(rid)

    mode_counts: dict[UUID, dict[str, int]] = {}
    rows = (
        db.query(
            ConnectorRunDocument.run_id,
            DBDocument.access_mode,
            func.count(DBDocument.id),
        )
        .join(DBDocument, DBDocument.id == ConnectorRunDocument.document_id)
        .filter(
            ConnectorRunDocument.tenant_id == tenant_id,
            ConnectorRunDocument.run_id.in_(normalized_run_ids),
        )
        .group_by(ConnectorRunDocument.run_id, DBDocument.access_mode)
        .all()
    )
    for run_id, access_mode, count in rows:
        mode = _normalize_doc_access_mode(access_mode)
        by = mode_counts.setdefault(run_id, {})
        by[mode] = int(by.get(mode, 0)) + int(count or 0)

    partial_member_counts_per_doc = (
        db.query(
            ConnectorRunDocument.run_id.label("run_id"),
            ConnectorRunDocument.document_id.label("document_id"),
            func.count(DocumentPermission.id).label("allowlist_count"),
        )
        .join(DBDocument, DBDocument.id == ConnectorRunDocument.document_id)
        .outerjoin(
            DocumentPermission,
            and_(
                DocumentPermission.tenant_id == tenant_id,
                DocumentPermission.document_id == ConnectorRunDocument.document_id,
            ),
        )
        .filter(
            ConnectorRunDocument.tenant_id == tenant_id,
            ConnectorRunDocument.run_id.in_(normalized_run_ids),
            func.lower(DBDocument.access_mode) == "partial_members",
        )
        .group_by(ConnectorRunDocument.run_id, ConnectorRunDocument.document_id)
        .subquery()
    )
    member_stats_rows = (
        db.query(
            partial_member_counts_per_doc.c.run_id,
            func.count(partial_member_counts_per_doc.c.document_id).label("doc_count"),
            func.min(partial_member_counts_per_doc.c.allowlist_count).label("min_count"),
            func.max(partial_member_counts_per_doc.c.allowlist_count).label("max_count"),
        )
        .group_by(partial_member_counts_per_doc.c.run_id)
        .all()
    )
    member_stats_by_run: dict[UUID, dict[str, int]] = {}
    for run_id, doc_count, min_count, max_count in member_stats_rows:
        member_stats_by_run[run_id] = {
            "partial_members_doc_count": int(doc_count or 0),
            "partial_member_count_min": int(min_count or 0),
            "partial_member_count_max": int(max_count or 0),
        }

    partial_group_counts_per_doc = (
        db.query(
            ConnectorRunDocument.run_id.label("run_id"),
            ConnectorRunDocument.document_id.label("document_id"),
            func.count(DocumentGroupPermission.id).label("allowlist_count"),
        )
        .join(DBDocument, DBDocument.id == ConnectorRunDocument.document_id)
        .outerjoin(
            DocumentGroupPermission,
            and_(
                DocumentGroupPermission.tenant_id == tenant_id,
                DocumentGroupPermission.document_id == ConnectorRunDocument.document_id,
            ),
        )
        .filter(
            ConnectorRunDocument.tenant_id == tenant_id,
            ConnectorRunDocument.run_id.in_(normalized_run_ids),
            func.lower(DBDocument.access_mode) == "partial_members",
        )
        .group_by(ConnectorRunDocument.run_id, ConnectorRunDocument.document_id)
        .subquery()
    )
    group_stats_rows = (
        db.query(
            partial_group_counts_per_doc.c.run_id,
            func.min(partial_group_counts_per_doc.c.allowlist_count).label("min_count"),
            func.max(partial_group_counts_per_doc.c.allowlist_count).label("max_count"),
        )
        .group_by(partial_group_counts_per_doc.c.run_id)
        .all()
    )
    group_stats_by_run: dict[UUID, dict[str, int]] = {}
    for run_id, min_count, max_count in group_stats_rows:
        group_stats_by_run[run_id] = {
            "partial_group_count_min": int(min_count or 0),
            "partial_group_count_max": int(max_count or 0),
        }

    out: dict[UUID, dict[str, Any]] = {}
    for rid in normalized_run_ids:
        counts = mode_counts.get(rid, {})
        documents_total = sum(int(v or 0) for v in counts.values())
        if documents_total <= 0:
            continue

        distinct_modes = [m for m, v in counts.items() if int(v or 0) > 0]
        mode = distinct_modes[0] if len(distinct_modes) == 1 else "mixed"

        summary: dict[str, Any] = {
            "mode": mode,
            "documents_total": int(documents_total),
            "access_mode_counts": counts,
        }

        partial_docs = int(counts.get("partial_members", 0) or 0)
        if partial_docs > 0:
            summary["partial_members_doc_count"] = int(partial_docs)

        summary.update(member_stats_by_run.get(rid, {}))
        summary.update(group_stats_by_run.get(rid, {}))
        out[rid] = summary

    return out


def _run_out(
    run: ConnectorRun,
    *,
    acl_summary: dict[str, Any] | None = None,
) -> ConnectorRunOut:
    leader = globals().get("_leader_module")
    db_connectors = getattr(leader, "_DB_CONNECTOR_IDS", set()) if leader is not None else set()
    docs = getattr(run, "documents", None) or []
    connector_id = str(getattr(run, "connector_id", "") or "").strip()
    config = redact_secrets(dict(run.config or {}))
    config = redact_connection_info(config, enabled=connector_id in db_connectors)
    return ConnectorRunOut(
        id=run.id,
        tenant_id=run.tenant_id,
        dataset_id=run.dataset_id,
        connector_id=connector_id,
        requested_by=(run.requested_by or None),
        status=str(run.status or "pending"),  # type: ignore[arg-type]
        config=config,
        stats=dict(run.stats or {}),
        error_message=(run.error_message or None),
        task_id=(run.task_id or None),
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
        acl_summary=(acl_summary or None),
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
    leader = globals().get("_leader_module")
    db_connectors = getattr(leader, "_DB_CONNECTOR_IDS", set()) if leader is not None else set()
    connector_id = str(cfg.connector_id or "").strip()
    config = redact_secrets(dict(cfg.config or {}))
    config = redact_connection_info(config, enabled=connector_id in db_connectors)
    return ConnectorConfigOut(
        id=cfg.id,
        tenant_id=cfg.tenant_id,
        dataset_id=cfg.dataset_id,
        connector_id=connector_id,
        name=str(cfg.name or ""),
        enabled=bool(cfg.enabled),
        schedule_cron=(str(cfg.schedule_cron).strip() if isinstance(cfg.schedule_cron, str) and cfg.schedule_cron.strip() else None),
        config=config,
        state=dict(cfg.state or {}),
        last_run_at=(cfg.last_run_at or None),
        last_error=(cfg.last_error or None),
        created_at=cfg.created_at,
        updated_at=cfg.updated_at,
    )


def _schedule_elapsed_seconds(*, now: datetime, last_run_at: datetime | None) -> float:
    if last_run_at is None:
        return 10**18
    try:
        return (now - last_run_at).total_seconds()
    except Exception:
        return 10**18


def _schedule_positive_int(raw: str) -> int | None:
    try:
        return max(1, int(raw))
    except Exception:
        return None


def _schedule_interval_from_parts(
    minute: str,
    hour: str,
    day: str,
    month: str,
    dow: str,
) -> int | None:
    step_patterns = (
        (minute.startswith("*/") and hour == "*" and day == "*" and month == "*" and dow == "*", minute[2:], 60),
        (minute == "0" and hour.startswith("*/") and day == "*" and month == "*" and dow == "*", hour[2:], 60 * 60),
        (minute == "0" and hour == "0" and day.startswith("*/") and month == "*" and dow == "*", day[2:], 60 * 60 * 24),
    )
    for matched, raw_value, multiplier in step_patterns:
        if not matched:
            continue
        value = _schedule_positive_int(raw_value)
        return None if value is None else multiplier * value
    return None


def _schedule_interval_seconds(schedule: str) -> int | None:
    raw = str(schedule or "").strip().lower()
    if not raw:
        return None

    fixed_intervals = {
        "@hourly": 60 * 60,
        "@daily": 60 * 60 * 24,
        "@weekly": 60 * 60 * 24 * 7,
        "@monthly": 60 * 60 * 24 * 30,
    }
    if raw in fixed_intervals:
        return fixed_intervals[raw]

    parts = raw.split()
    if len(parts) != 5:
        return None

    minute, hour, day, month, dow = parts
    return _schedule_interval_from_parts(minute, hour, day, month, dow)


def _schedule_due(
    *,
    schedule: str,
    now: datetime,
    last_run_at: datetime | None,
) -> bool:
    interval_sec = _schedule_interval_seconds(schedule)
    if interval_sec is None:
        return False
    return _schedule_elapsed_seconds(now=now, last_run_at=last_run_at) >= interval_sec


def _sync_connector_config_from_run(db: Session, *, run: ConnectorRun) -> None:
    leader = globals().get("_leader_module")
    stats = dict(getattr(run, "stats", None) or {})
    if leader is None:
        return

    raw_cfg_id = stats.get("config_id")
    cfg_id_str = (
        str(raw_cfg_id or "").strip()
        if isinstance(raw_cfg_id, (str, UUID))
        else ""
    )
    if not cfg_id_str:
        return
    try:
        cfg_uuid = UUID(cfg_id_str)
    except Exception:
        return

    cfg = (
        db.query(ConnectorConfig)
        .filter(
            ConnectorConfig.id == cfg_uuid,
            ConnectorConfig.tenant_id == run.tenant_id,
        )
        .first()
    )
    if cfg is None:
        return

    status = str(getattr(run, "status", "") or "").lower()
    cfg.last_error = None if status == "completed" else (str(getattr(run, "error_message", "") or status)[:200] or status)  # type: ignore[assignment]
    cfg.last_run_at = (
        getattr(run, "started_at", None)
        or getattr(run, "finished_at", None)
        or _now()
    )  # type: ignore[assignment]

    connector_id = str(getattr(run, "connector_id", "") or "").strip()
    cfg.state = build_saved_state_snapshot(  # type: ignore[assignment]
        connector_id=connector_id,
        existing_state=dict(getattr(cfg, "state", None) or {}),
        stats=stats,
        run_id=run.id,
        run_status=status,
        recorded_at=(
            getattr(run, "finished_at", None)
            or getattr(run, "started_at", None)
            or _now()
        ),
    )

    with contextlib.suppress(Exception):
        from app.services.audit_log_service import audit_log_event

        state = dict(getattr(cfg, "state", None) or {})
        state_audit = (
            state.get("state_audit")
            if isinstance(state.get("state_audit"), dict)
            else {}
        )
        audit_log_event(
            db,
            tenant_id=cfg.tenant_id,
            actor_id=(getattr(run, "requested_by", None) or None),
            action="connector_config.state.sync",
            resource_type="connector_config",
            resource_id=str(cfg.id),
            details={
                "config_id": str(cfg.id),
                "connector_id": connector_id,
                "run_id": str(run.id),
                "status": status,
                "schema_version": int(state.get("state_schema_version") or 0),
                "revision": int(state.get("state_revision") or 0),
                "updated_keys": list(state_audit.get("updated_keys") or []),
            },
        )

    db.commit()
