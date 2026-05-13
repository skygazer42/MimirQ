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

import logging
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.document import Document as DBDocument
from app.services.audit_log_retention import plan_audit_log_purge, purge_audit_log_rows
from app.services.audit_log_service import audit_log_event
from app.services.regression_run_retention import plan_regression_run_purge, purge_regression_run_rows

logger = logging.getLogger(__name__)
SYSTEM_RETENTION_ACTOR_ID = "system:retention"

_delete_document_lifecycle = None


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


def _normalize_lifecycle_state(value: str | None) -> str:
    out = str(value or "either").strip().lower()
    return out if out in {"archived", "disabled", "either"} else "either"


def _resolve_delete_document_lifecycle():  # noqa: ANN202
    global _delete_document_lifecycle
    if _delete_document_lifecycle is not None:
        return _delete_document_lifecycle
    from app.api.v1.documents import _delete_document_lifecycle as delete_document_lifecycle  # noqa: WPS433

    _delete_document_lifecycle = delete_document_lifecycle
    return _delete_document_lifecycle


def plan_knowledge_asset_purge(
    db: Session,
    *,
    tenant_id: UUID,
    cutoff: datetime,
    max_delete: int,
    dataset_id: UUID | None = None,
    lifecycle_state: str = "either",
) -> list[dict[str, Any]]:
    state = _normalize_lifecycle_state(lifecycle_state)
    limit = max(1, int(max_delete or 0))

    query = (
        db.query(
            DBDocument.id,
            DBDocument.dataset_id,
            DBDocument.archived_at,
            DBDocument.disabled_at,
        )
        .filter(DBDocument.tenant_id == tenant_id)
        .order_by(DBDocument.updated_at.asc(), DBDocument.id.asc())
    )
    if dataset_id is not None:
        query = query.filter(DBDocument.dataset_id == dataset_id)

    if state == "archived":
        query = query.filter(DBDocument.archived_at.isnot(None), DBDocument.archived_at <= cutoff)
    elif state == "disabled":
        query = query.filter(DBDocument.disabled_at.isnot(None), DBDocument.disabled_at <= cutoff)
    else:
        query = query.filter(
            ((DBDocument.archived_at.isnot(None)) & (DBDocument.archived_at <= cutoff))
            | ((DBDocument.disabled_at.isnot(None)) & (DBDocument.disabled_at <= cutoff))
        )

    rows = query.limit(limit).all()
    out: list[dict[str, Any]] = []
    for document_id, row_dataset_id, archived_at, disabled_at in rows:
        state_out = "archived" if archived_at is not None else "disabled"
        lifecycle_ts = archived_at if archived_at is not None else disabled_at
        out.append(
            {
                "document_id": document_id,
                "dataset_id": row_dataset_id,
                "lifecycle_state": state_out,
                "lifecycle_ts": lifecycle_ts,
            }
        )
    return out


def run_audit_log_retention(
    db: Session,
    *,
    tenant_id: UUID,
    retention_days: int,
    max_delete: int,
    dry_run: bool,
    actor_id: str | None = SYSTEM_RETENTION_ACTOR_ID,
    now: datetime | None = None,
) -> dict[str, Any]:
    """
    Run a bounded audit-log retention operation for one tenant.

    Returns a small PII-safe summary dict (counts and timestamps).
    """
    now0 = now or datetime.now(UTC)
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
        except Exception as exc:
            logger.debug("Ignoring non-critical retention fallback failure: %s", exc)

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

def run_regression_run_retention(
    db: Session,
    *,
    tenant_id: UUID,
    retention_days: int,
    max_delete: int,
    dry_run: bool,
    dataset_id: UUID | None = None,
    actor_id: str | None = SYSTEM_RETENTION_ACTOR_ID,
    now: datetime | None = None,
) -> dict[str, Any]:
    """
    Run a bounded regression-run retention operation for one tenant.

    Returns a small PII-safe summary dict (counts and timestamps).
    """
    now0 = now or datetime.now(UTC)
    try:
        retention_days_i = max(1, int(retention_days or 0))
    except Exception:
        retention_days_i = 90
    try:
        max_delete_i = max(1, int(max_delete or 0))
    except Exception:
        max_delete_i = 200
    max_delete_i = min(max_delete_i, 5000)

    cutoff = now0 - timedelta(days=int(retention_days_i))

    eligible = int(
        plan_regression_run_purge(
            db,
            tenant_id=tenant_id,
            cutoff=cutoff,
            max_delete=max_delete_i,
            dataset_id=dataset_id,
        )
        or 0
    )
    deleted_runs = 0
    deleted_items = 0
    if not bool(dry_run):
        deleted_runs, deleted_items = purge_regression_run_rows(
            db,
            tenant_id=tenant_id,
            cutoff=cutoff,
            max_delete=max_delete_i,
            dataset_id=dataset_id,
            commit=True,
        )

    # Best-effort: record the retention run itself (small, PII-safe).
    try:
        audit_log_event(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="evaluations.regression_runs.retention",
            resource_type="ragas_regression_runs",
            resource_id=str(dataset_id) if dataset_id is not None else None,
            details={
                "dry_run": bool(dry_run),
                "retention_days": int(retention_days_i),
                "cutoff": _dt_to_json(cutoff),
                "max_delete": int(max_delete_i),
                "eligible_runs": int(eligible),
                "deleted_runs": int(deleted_runs),
                "deleted_items": int(deleted_items),
                "ran_at": _dt_to_json(now0),
            },
        )
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception as exc:
            logger.debug("Ignoring non-critical retention fallback failure: %s", exc)

    return {
        "tenant_id": str(tenant_id),
        "dataset_id": str(dataset_id) if dataset_id is not None else None,
        "dry_run": bool(dry_run),
        "retention_days": int(retention_days_i),
        "cutoff": _dt_to_json(cutoff),
        "max_delete": int(max_delete_i),
        "eligible_runs": int(eligible),
        "deleted_runs": int(deleted_runs),
        "deleted_items": int(deleted_items),
        "ran_at": _dt_to_json(now0),
    }


async def run_knowledge_asset_retention(
    db: Session,
    *,
    tenant_id: UUID,
    retention_days: int,
    max_delete: int,
    dry_run: bool,
    dataset_id: UUID | None = None,
    lifecycle_state: str = "either",
    actor_id: str | None = SYSTEM_RETENTION_ACTOR_ID,
    now: datetime | None = None,
) -> dict[str, Any]:
    """
    Run a bounded retention operation for archived/disabled knowledge assets.

    Deletion is delegated to the existing document delete lifecycle so document
    rows, chunks, KG artifacts, vectors, and object assets stay aligned.
    """
    now0 = now or datetime.now(UTC)
    try:
        retention_days_i = max(1, int(retention_days or 0))
    except Exception:
        retention_days_i = 90
    try:
        max_delete_i = max(1, int(max_delete or 0))
    except Exception:
        max_delete_i = 1000

    state = _normalize_lifecycle_state(lifecycle_state)
    cutoff = now0 - timedelta(days=int(retention_days_i))
    planned = plan_knowledge_asset_purge(
        db,
        tenant_id=tenant_id,
        cutoff=cutoff,
        max_delete=max_delete_i,
        dataset_id=dataset_id,
        lifecycle_state=state,
    )

    deleted = 0
    not_found = 0
    denied = 0
    conflicts = 0
    errors = 0

    if not bool(dry_run):
        delete_document_lifecycle = _resolve_delete_document_lifecycle()
        for row in planned:
            document_id = row.get("document_id")
            if document_id is None:
                continue
            try:
                await delete_document_lifecycle(
                    document_id=document_id,
                    tenant_id=tenant_id,
                    account_id=str(actor_id or SYSTEM_RETENTION_ACTOR_ID),
                    db=db,
                    enforce_permissions=False,
                )
                deleted += 1
            except Exception as exc:  # noqa: BLE001
                status_code = getattr(exc, "status_code", None)
                if status_code == 404:
                    not_found += 1
                    continue
                if status_code in (401, 403):
                    denied += 1
                    continue
                if status_code in (409, 413, 429, 503):
                    conflicts += 1
                    continue
                errors += 1
                continue

    state_counts = Counter(str(row.get("lifecycle_state") or "unknown") for row in planned)
    summary = {
        "tenant_id": str(tenant_id),
        "dataset_id": str(dataset_id) if dataset_id is not None else None,
        "dry_run": bool(dry_run),
        "retention_days": int(retention_days_i),
        "cutoff": _dt_to_json(cutoff),
        "max_delete": int(max_delete_i),
        "lifecycle_state": state,
        "eligible": int(len(planned)),
        "deleted": int(deleted),
        "not_found": int(not_found),
        "denied": int(denied),
        "conflicts": int(conflicts),
        "errors": int(errors),
        "artifact_scopes": ["documents", "chunks", "kg", "vectors", "object_assets"],
        "eligible_by_state": dict(sorted((k, int(v)) for k, v in state_counts.items())),
        "ran_at": _dt_to_json(now0),
    }

    try:
        audit_log_event(
            db,
            tenant_id=tenant_id,
            actor_id=actor_id,
            action="knowledge.assets.retention",
            resource_type="documents",
            resource_id=str(dataset_id) if dataset_id is not None else None,
            details=summary,
        )
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception as exc:
            logger.debug("Ignoring non-critical retention fallback failure: %s", exc)

    return summary


__all__ = [
    "plan_knowledge_asset_purge",
    "run_audit_log_retention",
    "run_regression_run_retention",
    "run_knowledge_asset_retention",
]
