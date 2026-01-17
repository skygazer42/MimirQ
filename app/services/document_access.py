from typing import List, Optional, Set, Tuple
from uuid import UUID
from fastapi import HTTPException
from sqlalchemy.orm import Session
from app.models.document import Document as DBDocument
from app.services.dataset_service import DatasetService
from app.models.dataset import Dataset, DatasetPermission, DatasetPermissionEnum


def _resolve_allowed_dataset_ids(
    db: Session,
    tenant_id: UUID,
    account_id: str,
    dataset_ids: Set[UUID],
) -> Tuple[dict[UUID, Dataset], Set[UUID]]:
    if not dataset_ids:
        return {}, set()

    datasets = (
        db.query(Dataset)
        .filter(Dataset.tenant_id == tenant_id, Dataset.id.in_(list(dataset_ids)))
        .all()
    )
    dataset_map = {ds.id: ds for ds in datasets}

    allowed_dataset_ids: Set[UUID] = set()
    partial_dataset_ids: Set[UUID] = set()
    for ds in datasets:
        if ds.owner_id == account_id or ds.permission == DatasetPermissionEnum.ALL_TEAM_MEMBERS:
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

    return dataset_map, allowed_dataset_ids


def get_allowed_document_id_sets(
    db: Session,
    tenant_id: UUID,
    account_id: str,
    doc_ids: Optional[List[UUID]],
    *,
    check_member: bool = True,
) -> Tuple[Set[UUID], Set[UUID]]:
    """
    Resolve (allowed_ids, missing_ids) for a set of document IDs.

    - missing_ids: document ids not found under the tenant
    - allowed_ids: ids the account can read (legacy docs without dataset are allowed)
    """
    if check_member:
        DatasetService.ensure_member(db, tenant_id, account_id)
    if not doc_ids:
        return set(), set()

    documents = (
        db.query(DBDocument.id, DBDocument.dataset_id)
        .filter(
            DBDocument.tenant_id == tenant_id,
            DBDocument.id.in_(doc_ids),
        )
        .all()
    )

    found_ids = {doc_id for doc_id, _ in documents}
    missing_ids = set(doc_ids) - found_ids

    dataset_ids = {dataset_id for _, dataset_id in documents if dataset_id}
    dataset_map, allowed_dataset_ids = _resolve_allowed_dataset_ids(db, tenant_id, account_id, dataset_ids)

    allowed_ids: Set[UUID] = set()
    for doc_id, dataset_id in documents:
        if not dataset_id:
            # legacy document without dataset binding: allow for now
            allowed_ids.add(doc_id)
            continue
        if dataset_id not in dataset_map:
            continue
        if dataset_id in allowed_dataset_ids:
            allowed_ids.add(doc_id)

    return allowed_ids, missing_ids


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
    DatasetService.ensure_member(db, tenant_id, account_id)
    if not doc_ids:
        return []

    allowed_ids, missing_ids = get_allowed_document_id_sets(
        db,
        tenant_id,
        account_id,
        doc_ids,
        check_member=False,
    )
    if missing_ids:
        missing = [str(doc_id) for doc_id in doc_ids if doc_id in missing_ids]
        raise HTTPException(status_code=404, detail=f"Documents not found: {', '.join(missing)}")

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
    DatasetService.ensure_member(db, tenant_id, account_id)
    query = (
        db.query(DBDocument.id, DBDocument.dataset_id, DBDocument.updated_at)
        .filter(DBDocument.tenant_id == tenant_id)
    )
    if status:
        query = query.filter(DBDocument.status == status)

    query = query.order_by(DBDocument.updated_at.desc())
    if limit and limit > 0:
        query = query.limit(limit)

    documents = query.all()
    if not documents:
        return []

    # Documents without dataset binding are treated as legacy and allowed.
    dataset_ids = {dataset_id for _, dataset_id, _ in documents if dataset_id}
    if not dataset_ids:
        return [doc_id for doc_id, _, _ in documents]

    dataset_map, allowed_dataset_ids = _resolve_allowed_dataset_ids(db, tenant_id, account_id, dataset_ids)

    accessible: List[UUID] = []
    for doc_id, dataset_id, _ in documents:
        if not dataset_id:
            accessible.append(doc_id)
            continue
        if dataset_id not in dataset_map:
            continue
        if dataset_id in allowed_dataset_ids:
            accessible.append(doc_id)
    return accessible
