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
    requested_document_ids = set(document_ids)
    if not requested_document_ids:
        return None

    rows = (
        db.query(DBDocument.id, DBDocument.dataset_id)
        .filter(DBDocument.tenant_id == tenant_id, DBDocument.id.in_(requested_document_ids))
        .all()
    )
    if {row[0] for row in rows} != requested_document_ids:
        return None
    dataset_ids = {row[1] for row in rows}
    if len(dataset_ids) != 1:
        return None
    only = next(iter(dataset_ids))
    return only


def load_dataset_metadata(
    db: Session,
    *,
    tenant_id: UUID,
    dataset_id: UUID,
) -> dict[str, Any]:
    """Load dataset metadata JSON safely (returns {} when missing/invalid)."""
    row = db.query(Dataset).filter(Dataset.tenant_id == tenant_id, Dataset.id == dataset_id).first()
    if row is None:
        return {}
    meta = row.dataset_metadata
    return dict(meta) if isinstance(meta, dict) else {}
