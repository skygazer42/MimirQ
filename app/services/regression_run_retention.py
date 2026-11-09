"""
Regression run retention helpers.

Bounded, auditable purge operations for:
- ragas_regression_runs
- ragas_regression_items

These helpers are intentionally small and DB-only (no heavy ML deps) so they can
be used by:
- admin-only API endpoints
- retention job runners (cron / Kubernetes CronJob)
"""

from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.evaluation import RagasRegressionItem, RagasRegressionRun

if TYPE_CHECKING:
    from sqlalchemy.orm import Query


def _base_query(
    db: Session,
    *,
    tenant_id: UUID,
    cutoff: datetime,
    dataset_id: UUID | None = None,
) -> "Query[tuple[UUID]]":
    q = (
        db.query(RagasRegressionRun.id)
        .filter(
            RagasRegressionRun.tenant_id == tenant_id,
            RagasRegressionRun.status.in_(["completed", "failed"]),
            RagasRegressionRun.finished_at.isnot(None),
            RagasRegressionRun.finished_at < cutoff,
        )
        .order_by(RagasRegressionRun.finished_at.asc())
    )
    if dataset_id is not None:
        q = q.filter(RagasRegressionRun.dataset_id == dataset_id)
    return q


def _candidate_run_ids(
    db: Session,
    *,
    tenant_id: UUID,
    cutoff: datetime,
    max_delete: int,
    dataset_id: UUID | None,
) -> list[UUID]:
    # Keep the existing maintenance ceiling for direct API and job callers.
    limit = min(max(1, int(max_delete)), 5000)
    rows = _base_query(db, tenant_id=tenant_id, cutoff=cutoff, dataset_id=dataset_id).limit(limit).all()
    return [run_id for (run_id,) in rows]


def plan_regression_run_purge(
    db: Session,
    *,
    tenant_id: UUID,
    cutoff: datetime,
    max_delete: int,
    dataset_id: UUID | None = None,
) -> int:
    """
    Return how many runs *would* be deleted for this purge run (bounded by max_delete).
    """
    return len(_candidate_run_ids(db, tenant_id=tenant_id, cutoff=cutoff, max_delete=max_delete, dataset_id=dataset_id))


def purge_regression_run_rows(
    db: Session,
    *,
    tenant_id: UUID,
    cutoff: datetime,
    max_delete: int,
    dataset_id: UUID | None = None,
    commit: bool = True,
) -> tuple[int, int]:
    """
    Delete old regression runs + items (bounded).

    Returns:
        (deleted_runs, deleted_items)
    """
    run_ids = _candidate_run_ids(db, tenant_id=tenant_id, cutoff=cutoff, max_delete=max_delete, dataset_id=dataset_id)
    if not run_ids:
        return (0, 0)

    deleted_items = (
        db.query(RagasRegressionItem)
        .filter(RagasRegressionItem.tenant_id == tenant_id, RagasRegressionItem.run_id.in_(run_ids))
        .delete(synchronize_session=False)
    )
    deleted_runs = (
        db.query(RagasRegressionRun)
        .filter(RagasRegressionRun.tenant_id == tenant_id, RagasRegressionRun.id.in_(run_ids))
        .delete(synchronize_session=False)
    )
    if commit:
        db.commit()

    return (deleted_runs, deleted_items)


__all__ = ["plan_regression_run_purge", "purge_regression_run_rows"]
