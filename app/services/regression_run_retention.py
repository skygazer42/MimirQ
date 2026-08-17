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
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.evaluation import RagasRegressionItem, RagasRegressionRun


def _base_query(
    db: Session,
    *,
    tenant_id: UUID,
    cutoff: datetime,
    dataset_id: UUID | None = None,
):
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
    try:
        max_delete_i = max(1, int(max_delete or 0))
    except Exception:
        max_delete_i = 200
    # Safety: avoid accidental mass-deletes from misconfigured cron args.
    max_delete_i = min(max_delete_i, 5000)

    total = int(_base_query(db, tenant_id=tenant_id, cutoff=cutoff, dataset_id=dataset_id).count() or 0)
    return min(total, max_delete_i)


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
    try:
        max_delete_i = max(1, int(max_delete or 0))
    except Exception:
        max_delete_i = 200
    max_delete_i = min(max_delete_i, 5000)

    run_ids: list[UUID] = [
        row[0]
        for row in _base_query(db, tenant_id=tenant_id, cutoff=cutoff, dataset_id=dataset_id).limit(max_delete_i).all()
        if row and row[0] is not None
    ]
    if not run_ids:
        return (0, 0)

    deleted_items = int(
        db.query(RagasRegressionItem)
        .filter(RagasRegressionItem.tenant_id == tenant_id, RagasRegressionItem.run_id.in_(run_ids))
        .delete(synchronize_session=False)
        or 0
    )
    deleted_runs = int(
        db.query(RagasRegressionRun)
        .filter(RagasRegressionRun.tenant_id == tenant_id, RagasRegressionRun.id.in_(run_ids))
        .delete(synchronize_session=False)
        or 0
    )
    if bool(commit):
        db.commit()

    return (deleted_runs, deleted_items)


__all__ = ["plan_regression_run_purge", "purge_regression_run_rows"]
