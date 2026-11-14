"""
Audit log retention helpers.

Goal:
- Support enterprise lifecycle controls (retention/purge) with bounded, auditable operations.

Notes:
- Planning and deletion failures propagate to the admin API or maintenance job.
- Recording the maintenance operation itself remains a separate audit-log sidecar.
- Keep outputs PII-minimal: return counts only by default.
"""

from collections.abc import Sequence
from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import Query, Session

from app.models.audit_log import AuditLog
from app.rag.core.logging import get_logger
from app.services.audit_log_service import apply_audit_log_filters

logger = get_logger(__name__)

BOUNDED_DELETE_FAILED_LOG = "audit-log purge: bounded delete failed, rolled back: %s"


def _candidate_ids_from_query(q: Query, *, max_delete: int) -> list[UUID]:
    rows = q.order_by(AuditLog.created_at.asc(), AuditLog.id.asc()).limit(max_delete).all()
    return [row_id for (row_id,) in rows]


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
    candidate_ids = _candidate_ids_from_query(
        db.query(AuditLog.id).filter(AuditLog.tenant_id == tenant_id, AuditLog.created_at < cutoff),
        max_delete=max_delete,
    )
    return len(candidate_ids)


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

    Returns the number of deleted rows; database failures propagate.
    """
    candidate_ids = _candidate_ids_from_query(
        db.query(AuditLog.id).filter(AuditLog.tenant_id == tenant_id, AuditLog.created_at < cutoff),
        max_delete=max_delete,
    )

    return delete_audit_log_rows(db, tenant_id=tenant_id, ids=candidate_ids, commit=commit)


def plan_filtered_audit_log_purge(
    db: Session,
    *,
    tenant_id: UUID,
    max_delete: int,
    actor_id: str | None = None,
    action: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    request_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> int:
    """Return bounded row count for a filter-scoped audit-log purge."""
    q = apply_audit_log_filters(
        db.query(AuditLog.id).filter(AuditLog.tenant_id == tenant_id),
        actor_id=actor_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        request_id=request_id,
        since=since,
        until=until,
    )
    return len(_candidate_ids_from_query(q, max_delete=max_delete))


def purge_filtered_audit_log_rows(
    db: Session,
    *,
    tenant_id: UUID,
    max_delete: int,
    actor_id: str | None = None,
    action: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    request_id: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    commit: bool = True,
) -> int:
    """Delete rows matching explicit filters for a tenant, bounded by max_delete."""
    q = apply_audit_log_filters(
        db.query(AuditLog.id).filter(AuditLog.tenant_id == tenant_id),
        actor_id=actor_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        request_id=request_id,
        since=since,
        until=until,
    )
    candidate_ids = _candidate_ids_from_query(q, max_delete=max_delete)

    return delete_audit_log_rows(db, tenant_id=tenant_id, ids=candidate_ids, commit=commit)


def delete_audit_log_rows(
    db: Session,
    *,
    tenant_id: UUID,
    ids: Sequence[UUID],
    commit: bool = True,
) -> int:
    """Delete explicit audit log rows for a tenant, bounded by the caller-provided id list."""
    unique_ids = list(dict.fromkeys(ids))
    if not unique_ids:
        return 0

    try:
        deleted = (
            db.query(AuditLog)
            .filter(AuditLog.tenant_id == tenant_id, AuditLog.id.in_(unique_ids))
            .delete(synchronize_session=False)
        )
        if commit:
            db.commit()
        else:
            db.flush()
        return deleted
    except Exception as exc:
        db.rollback()
        logger.warning(BOUNDED_DELETE_FAILED_LOG, exc, exc_info=True)
        raise


__all__ = [
    "delete_audit_log_rows",
    "plan_audit_log_purge",
    "plan_filtered_audit_log_purge",
    "purge_filtered_audit_log_rows",
    "purge_audit_log_rows",
]
