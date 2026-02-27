"""
Retention job helpers (enterprise lifecycle automation).

This module provides small, testable building blocks that can be triggered by:
- a CLI runner (cronjob / Kubernetes CronJob)
- a queue worker job (arq) if desired
- an admin-only API endpoint (optional)

Principles:
- Bounded deletes (caller provides max_delete)
- Auditable (records a small audit log event)
- Fail-open: retention must never crash product flows
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.services.audit_log_retention import plan_audit_log_purge, purge_audit_log_rows
from app.services.audit_log_service import audit_log_event


def _dt_to_json(v: datetime | None) -> str | None:
    if v is None:
        return None
    try:
        s = v.isoformat()
    except Exception:
        return None
    if s.endswith("+00:00"):
        s = s[:-6] + "Z"
    return s


def run_audit_log_retention(
    db: Session,
    *,
    tenant_id: UUID,
    retention_days: int,
    max_delete: int,
    dry_run: bool,
    actor_id: str | None = "system:retention",
    now: datetime | None = None,
) -> dict[str, Any]:
    """
    Run a bounded audit-log retention operation for one tenant.

    Returns a small PII-safe summary dict (counts and timestamps).
    """
    now0 = now or datetime.now(timezone.utc)
    try:
        retention_days_i = max(1, int(retention_days or 0))
    except Exception:
        retention_days_i = 90
    try:
        max_delete_i = max(1, int(max_delete or 0))
    except Exception:
        max_delete_i = 100_000

    cutoff = now0 - timedelta(days=int(retention_days_i))

    eligible = int(plan_audit_log_purge(db, tenant_id=tenant_id, cutoff=cutoff, max_delete=max_delete_i) or 0)
    deleted = 0
    if not bool(dry_run):
        deleted = int(
            purge_audit_log_rows(db, tenant_id=tenant_id, cutoff=cutoff, max_delete=max_delete_i, commit=True) or 0
        )

    # Best-effort: record the retention run itself (small, PII-safe).
    try:
        audit_log_event(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="audit.logs.retention",
            resource_type="audit_logs",
            resource_id=None,
            details={
                "dry_run": bool(dry_run),
                "retention_days": int(retention_days_i),
                "cutoff": _dt_to_json(cutoff),
                "max_delete": int(max_delete_i),
                "eligible": int(eligible),
                "deleted": int(deleted),
                "ran_at": _dt_to_json(now0),
            },
        )
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass

    return {
        "tenant_id": str(tenant_id),
        "dry_run": bool(dry_run),
        "retention_days": int(retention_days_i),
        "cutoff": _dt_to_json(cutoff),
        "max_delete": int(max_delete_i),
        "eligible": int(eligible),
        "deleted": int(deleted),
        "ran_at": _dt_to_json(now0),
    }


__all__ = ["run_audit_log_retention"]

