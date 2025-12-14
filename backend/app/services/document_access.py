from typing import List, Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.document import Document as DBDocument
from app.services.dataset_service import DatasetService


def filter_allowed_document_ids(
    db: Session,
    tenant_id: UUID,
    account_id: str,
    doc_ids: Optional[List[UUID]],
) -> List[UUID]:
    """
    Validate documents exist under tenant and enforce dataset read permissions.
    Returns the list of allowed document IDs (preserves input order when possible).
    """
    if not doc_ids:
        return []

    documents = (
        db.query(DBDocument)
        .filter(
            DBDocument.tenant_id == tenant_id,
            DBDocument.id.in_(doc_ids),
        )
        .all()
    )

    found_ids = {doc.id for doc in documents}
    missing = set(doc_ids) - found_ids
    if missing:
        raise HTTPException(
            status_code=404,
            detail=f"Documents not found: {', '.join([str(m) for m in missing])}",
        )

    allowed_ids: set[UUID] = set()
    for doc in documents:
        if doc.dataset_id:
            ds = DatasetService.get_dataset(db, tenant_id, doc.dataset_id)
            if DatasetService.check_dataset_permission(db, ds, account_id):
                allowed_ids.add(doc.id)
        else:
            # legacy document without dataset binding: allow for now
            allowed_ids.add(doc.id)

    if not allowed_ids:
        raise HTTPException(status_code=403, detail="No accessible documents for this request")

    # preserve input ordering
    return [doc_id for doc_id in doc_ids if doc_id in allowed_ids]
