"""
Periodic job freshness snapshot (ops-facing).

Provides a small admin-only endpoint to answer:
  - "When did our periodic audits / access review last run?"
  - "Are we stale?"

Design goals:
- Tenant-scoped, PII-safe: no user/account identifiers in the payload.
- Bounded: constant-size response (one item per known periodic job).
- Cheap: at most one indexed query per job (latest audit log row).
"""


from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog

PERIODIC_JOB_FRESHNESS_SCHEMA_V1 = "mimirq.periodic_job_freshness.v1"


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _as_utc(dt: datetime) -> datetime:
    """
    Normalize datetimes to timezone-aware UTC.

    Note: DB timestamps should already be tz-aware; this is defensive for tests/mocks.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    try:
        return dt.astimezone(UTC)
    except Exception:
        return dt


@dataclass(frozen=True)
class PeriodicJobSpec:
    key: str
    action: str
    resource_type: str
    expected_interval_hours: int
    stale_after_hours: int


_DAILY = 24
_DEFAULT_STALE_AFTER_HOURS = 36  # 1.5 days: tolerate cron jitter + outages but still catch real staleness.

_SPECS: tuple[PeriodicJobSpec, ...] = (
    PeriodicJobSpec(
        key="index_audit_daily",
        action="observability.index_audit.daily",
        resource_type="index_audit_report",
        expected_interval_hours=_DAILY,
        stale_after_hours=_DEFAULT_STALE_AFTER_HOURS,
    ),
    PeriodicJobSpec(
        key="embedding_drift_daily",
        action="observability.embedding_drift.daily",
        resource_type="embedding_drift_report",
        expected_interval_hours=_DAILY,
        stale_after_hours=_DEFAULT_STALE_AFTER_HOURS,
    ),
    PeriodicJobSpec(
        key="evidence_drift_daily",
        action="evidence.drift_audit.daily",
        resource_type="evidence_drift_report",
        expected_interval_hours=_DAILY,
        stale_after_hours=_DEFAULT_STALE_AFTER_HOURS,
    ),
    PeriodicJobSpec(
        key="access_review_daily",
        action="compliance.access_review.daily",
        resource_type="access_review_summary",
        expected_interval_hours=_DAILY,
        stale_after_hours=_DEFAULT_STALE_AFTER_HOURS,
    ),
)


def _latest_audit_event(
    db: Session,
    *,
    tenant_id: UUID,
    action: str,
    resource_type: str,
) -> dict[str, Any] | None:
    """
    Return {"created_at": datetime, "resource_id": str|None} for the latest event, or None.

    This is intentionally PII-minimal and avoids pulling `details` unless needed.
    """
    if db is None:
        return None
    try:
        row = (
            db.query(AuditLog.created_at, AuditLog.resource_id)
            .filter(
                AuditLog.tenant_id == tenant_id,
                AuditLog.action == str(action),
                AuditLog.resource_type == str(resource_type),
            )
            .order_by(desc(AuditLog.created_at), desc(AuditLog.id))
            .limit(1)
            .first()
        )
    except Exception:
        return None

    if not row:
        return None

    created_at = row[0] if isinstance(row, tuple) and len(row) > 0 else None
    resource_id = row[1] if isinstance(row, tuple) and len(row) > 1 else None
    if not isinstance(created_at, datetime):
        return None

    return {"created_at": _as_utc(created_at), "resource_id": (str(resource_id) if resource_id is not None else None)}


def build_periodic_job_freshness_snapshot(
    *,
    db: Session,
    tenant_id: UUID,
    now: datetime | None = None,
) -> dict[str, Any]:
    """
    Build a bounded snapshot of periodic job freshness for one tenant.
    """
    now0 = _as_utc(now or _now_utc())

    items: list[dict[str, Any]] = []
    for spec in _SPECS:
        latest = _latest_audit_event(
            db,
            tenant_id=tenant_id,
            action=spec.action,
            resource_type=spec.resource_type,
        )
        created_at: datetime | None = None
        resource_id: str | None = None
        if isinstance(latest, dict):
            if isinstance(latest.get("created_at"), datetime):
                created_at = _as_utc(latest["created_at"])
            rid = latest.get("resource_id")
            resource_id = (str(rid) if rid is not None else None)

        age_seconds: int | None = None
        stale = True
        if created_at is not None:
            try:
                age = now0 - created_at
                age_seconds = max(0, int(age.total_seconds()))
            except Exception:
                age_seconds = None

        stale_after_sec = max(1, int(spec.stale_after_hours) * 3600)
        if age_seconds is not None and age_seconds <= stale_after_sec:
            stale = False

        items.append(
            {
                "key": spec.key,
                "action": spec.action,
                "resource_type": spec.resource_type,
                "expected_interval_hours": int(spec.expected_interval_hours),
                "stale_after_hours": int(spec.stale_after_hours),
                "last_created_at": created_at,
                "last_resource_id": resource_id,
                "age_seconds": age_seconds,
                "stale": bool(stale),
            }
        )

    return {
        "schema": PERIODIC_JOB_FRESHNESS_SCHEMA_V1,
        "generated_at": now0,
        "tenant_id": str(tenant_id),
        "items": items,
    }


__all__ = [
    "PERIODIC_JOB_FRESHNESS_SCHEMA_V1",
    "build_periodic_job_freshness_snapshot",
]
