"""
Audit log retention helpers.

Goal:
- Support enterprise lifecycle controls (retention/purge) with bounded, auditable operations.

Notes:
- Best-effort: purge should never crash product flows, but it is an admin-only endpoint.
- Keep outputs PII-minimal: return counts only by default.
"""

from __future__ import annotations

import contextlib
from datetime import datetime
from typing import Sequence
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.audit_log import AuditLog


def _coerce_uuid_list(rows: Sequence[object]) -> list[UUID]:
    out: list[UUID] = []
    for r in rows:
        if not r:
            continue
        value = None
        if isinstance(r, tuple) and r:
            value = r[0]
        else:
            value = r
        if isinstance(value, UUID):
            out.append(value)
    return out


def plan_audit_log_purge(
    db: Session,
    *,
    tenant_id: UUID,
    cutoff: datetime,
    max_delete: int,
) -> int:
    """
    Return how many rows *would* be deleted for this purge run (bounded by max_delete).

    This intentionally avoids an unbounded COUNT(*) on very large audit tables.
    """
    try:
        rows = (
            db.query(AuditLog.id)
            .filter(AuditLog.tenant_id == tenant_id, AuditLog.created_at < cutoff)
            .order_by(AuditLog.created_at.asc(), AuditLog.id.asc())
            .limit(int(max_delete or 0))
            .all()
        )
        return len(_coerce_uuid_list(rows))
    except Exception:
        return 0


def purge_audit_log_rows(
    db: Session,
    *,
    tenant_id: UUID,
    cutoff: datetime,
    max_delete: int,
    commit: bool = True,
) -> int:
    """
    Delete audit log rows older than cutoff for a tenant, bounded by max_delete.

    Returns the number of deleted rows (best-effort).
    """
    candidate_ids: list[UUID] = []
    try:
        rows = (
            db.query(AuditLog.id)
            .filter(AuditLog.tenant_id == tenant_id, AuditLog.created_at < cutoff)
            .order_by(AuditLog.created_at.asc(), AuditLog.id.asc())
            .limit(int(max_delete or 0))
            .all()
        )
        candidate_ids = _coerce_uuid_list(rows)
    except Exception:
        candidate_ids = []

    if not candidate_ids:
        return 0

    deleted = 0
    try:
        deleted = int(
            db.query(AuditLog)
            .filter(AuditLog.tenant_id == tenant_id, AuditLog.id.in_(candidate_ids))
            .delete(synchronize_session=False)
            or 0
        )
        if commit:
            db.commit()
        else:
            with contextlib.suppress(Exception):
                db.flush()
    except Exception:
        with contextlib.suppress(Exception):
            db.rollback()
        return 0

    return deleted


__all__ = [
    "plan_audit_log_purge",
    "purge_audit_log_rows",
]

