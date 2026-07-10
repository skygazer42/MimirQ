"""
Dataset defaults helpers.

These utilities keep "per-dataset defaults" logic out of API endpoints so it can be reused by:
- chat endpoints
- RAG preview endpoints
- future workers/tasks (ingestion, evaluation, etc.)
"""


from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.dataset import Dataset
from app.models.document import Document as DBDocument


def resolve_single_dataset_id_for_documents(
    db: Session,
    *,
    tenant_id: UUID,
    document_ids: list[UUID],
) -> UUID | None:
    """
    Return the dataset_id if and only if all documents belong to the same non-null dataset.

    If documents span multiple datasets (or include NULL dataset_id), returns None.
    """
    if not document_ids:
        return None

    rows = (
        db.query(DBDocument.dataset_id)
        .filter(DBDocument.tenant_id == tenant_id, DBDocument.id.in_(list(document_ids)))
        .distinct()
        .all()
    )
    ids = {r[0] for r in rows}
    if len(ids) != 1:
        return None
    only = next(iter(ids))
    return only if only is not None else None


def load_dataset_metadata(
    db: Session,
    *,
    tenant_id: UUID,
    dataset_id: UUID,
) -> dict[str, Any]:
    """Load dataset metadata JSON safely (returns {} when missing/invalid)."""
    row = (
        db.query(Dataset)
        .filter(Dataset.tenant_id == tenant_id, Dataset.id == dataset_id)
        .first()
    )
    if row is None:
        return {}
    meta = getattr(row, "dataset_metadata", None)
    return dict(meta) if isinstance(meta, dict) else {}

