from typing import List, Optional
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.document import Document as DBDocument
from app.services.dataset_service import DatasetService
from app.models.dataset import Dataset, DatasetPermission, DatasetPermissionEnum


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


def list_accessible_document_ids(
    db: Session,
    tenant_id: UUID,
    account_id: str,
    *,
    status: str | None = "completed",
    limit: int | None = 200,
) -> List[UUID]:
    """
    List accessible document IDs under a tenant for the current account.

    This is a batched/efficient variant for "default scope" scenarios (e.g. chat without explicit document_ids).
    It enforces dataset permissions without issuing 1 query per document.
    """
    query = db.query(DBDocument).filter(DBDocument.tenant_id == tenant_id)
    if status:
        query = query.filter(DBDocument.status == status)

    query = query.order_by(DBDocument.updated_at.desc())
    if limit and limit > 0:
        query = query.limit(limit)

    documents = query.all()
    if not documents:
        return []

    # Documents without dataset binding are treated as legacy and allowed.
    dataset_ids = {doc.dataset_id for doc in documents if doc.dataset_id}
    if not dataset_ids:
        return [doc.id for doc in documents]

    datasets = (
        db.query(Dataset)
        .filter(Dataset.tenant_id == tenant_id, Dataset.id.in_(list(dataset_ids)))
        .all()
    )
    dataset_map = {ds.id: ds for ds in datasets}

    allowed_dataset_ids: set[UUID] = set()
    partial_dataset_ids: set[UUID] = set()
    for ds in datasets:
        if ds.owner_id == account_id:
            allowed_dataset_ids.add(ds.id)
            continue
        if ds.permission == DatasetPermissionEnum.ALL_TEAM_MEMBERS:
            allowed_dataset_ids.add(ds.id)
            continue
        if ds.permission == DatasetPermissionEnum.PARTIAL_MEMBERS:
            partial_dataset_ids.add(ds.id)

    if partial_dataset_ids:
        rows = (
            db.query(DatasetPermission.dataset_id)
            .filter(
                DatasetPermission.tenant_id == tenant_id,
                DatasetPermission.account_id == account_id,
                DatasetPermission.dataset_id.in_(list(partial_dataset_ids)),
            )
            .all()
        )
        allowed_dataset_ids.update(row[0] for row in rows)

    accessible: List[UUID] = []
    for doc in documents:
        if not doc.dataset_id:
            accessible.append(doc.id)
            continue
        ds = dataset_map.get(doc.dataset_id)
        if not ds:
            continue
        if ds.permission == DatasetPermissionEnum.ONLY_ME and ds.owner_id != account_id:
            continue
        if doc.dataset_id in allowed_dataset_ids:
            accessible.append(doc.id)
    return accessible
