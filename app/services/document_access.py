from typing import List, Optional, Set, Tuple
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.dataset import Dataset, DatasetPermission, DatasetPermissionEnum
from app.models.document import Document as DBDocument
from app.models.document import DocumentPermission
from app.models.group_permissions import DatasetGroupPermission, DocumentGroupPermission
from app.models.tenant_group import TenantGroupMember
from app.services.dataset_service import DatasetService

# Document-level ACL ("security trimming") modes.
_DOC_ACCESS_DEFAULTS = {"", "inherit"}
_DOC_ACCESS_ALL = "all_team_members"
_DOC_ACCESS_OWNER_ONLY = "only_me"
_DOC_ACCESS_PARTIAL = "partial_members"


def _resolve_account_group_ids(db: Session, *, tenant_id: UUID, account_id: str) -> Set[UUID]:
    """
    Resolve tenant-scoped group ids for an account.

    Note: this is a low-level helper used by permission checks; it must not raise
    for missing memberships (empty set means "no groups").
    """
    uid = (str(account_id or "")).strip()
    if not uid:
        return set()
    rows = (
        db.query(TenantGroupMember.group_id)
        .filter(
            TenantGroupMember.tenant_id == tenant_id,
            TenantGroupMember.user_id == uid,
        )
        .all()
    )
    return {row[0] for row in rows if row and row[0]}


def _normalize_doc_access_mode(value: object) -> str:
    return (str(value or "")).strip().lower()


def _doc_access_allows(
    *,
    doc_id: UUID,
    access_mode: object,
    owner_id: object,
    account_id: str,
    allowlist_doc_ids: Set[UUID],
) -> bool:
    """
    Evaluate document-level ACL for a single doc.

    Notes:
    - Dataset-level permissions are enforced separately; this only checks document overrides.
    - Unknown modes fail closed for defense-in-depth.
    """
    mode = _normalize_doc_access_mode(access_mode)
    owner = (str(owner_id or "")).strip()

    if mode in _DOC_ACCESS_DEFAULTS or mode == _DOC_ACCESS_ALL:
        return True

    if mode == _DOC_ACCESS_OWNER_ONLY:
        return bool(owner and owner == account_id)

    if mode == _DOC_ACCESS_PARTIAL:
        if owner and owner == account_id:
            return True
        return doc_id in allowlist_doc_ids

    return False


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

        group_ids = _resolve_account_group_ids(db, tenant_id=tenant_id, account_id=account_id)
        if group_ids:
            rows = (
                db.query(DatasetGroupPermission.dataset_id)
                .filter(
                    DatasetGroupPermission.tenant_id == tenant_id,
                    DatasetGroupPermission.dataset_id.in_(list(partial_dataset_ids)),
                    DatasetGroupPermission.group_id.in_(list(group_ids)),
                )
                .all()
            )
            allowed_dataset_ids.update(row[0] for row in rows if row and row[0])

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
        db.query(DBDocument.id, DBDocument.dataset_id, DBDocument.access_mode, DBDocument.owner_id)
        .filter(
            DBDocument.tenant_id == tenant_id,
            DBDocument.id.in_(doc_ids),
        )
        .all()
    )

    found_ids = {doc_id for doc_id, *_ in documents}
    missing_ids = set(doc_ids) - found_ids

    dataset_ids = {dataset_id for _, dataset_id, *_ in documents if dataset_id}
    dataset_map, allowed_dataset_ids = _resolve_allowed_dataset_ids(db, tenant_id, account_id, dataset_ids)

    # Batch fetch allowlist membership for docs that require it.
    doc_ids_needing_allowlist: list[UUID] = []
    for doc_id, _dataset_id, access_mode, owner_id in documents:
        mode = _normalize_doc_access_mode(access_mode)
        if mode == _DOC_ACCESS_PARTIAL and (str(owner_id or "").strip() != account_id):
            doc_ids_needing_allowlist.append(doc_id)

    allowlist_doc_ids: Set[UUID] = set()
    if doc_ids_needing_allowlist:
        rows = (
            db.query(DocumentPermission.document_id)
            .filter(
                DocumentPermission.tenant_id == tenant_id,
                DocumentPermission.account_id == account_id,
                DocumentPermission.document_id.in_(doc_ids_needing_allowlist),
            )
            .all()
        )
        allowlist_doc_ids = {row[0] for row in rows if row and row[0]}
        group_ids = _resolve_account_group_ids(db, tenant_id=tenant_id, account_id=account_id)
        if group_ids:
            rows = (
                db.query(DocumentGroupPermission.document_id)
                .filter(
                    DocumentGroupPermission.tenant_id == tenant_id,
                    DocumentGroupPermission.document_id.in_(doc_ids_needing_allowlist),
                    DocumentGroupPermission.group_id.in_(list(group_ids)),
                )
                .all()
            )
            allowlist_doc_ids.update({row[0] for row in rows if row and row[0]})

    allowed_ids: Set[UUID] = set()
    for doc_id, dataset_id, access_mode, owner_id in documents:
        if not dataset_id:
            # legacy document without dataset binding: allow for now
            if _doc_access_allows(
                doc_id=doc_id,
                access_mode=access_mode,
                owner_id=owner_id,
                account_id=account_id,
                allowlist_doc_ids=allowlist_doc_ids,
            ):
                allowed_ids.add(doc_id)
            continue
        if dataset_id not in dataset_map:
            continue
        if dataset_id in allowed_dataset_ids:
            ds = dataset_map.get(dataset_id)
            # Dataset owner can always access docs in their dataset (admin/management use-case).
            if ds is not None and str(getattr(ds, "owner_id", "") or "") == account_id:
                allowed_ids.add(doc_id)
                continue
            if _doc_access_allows(
                doc_id=doc_id,
                access_mode=access_mode,
                owner_id=owner_id,
                account_id=account_id,
                allowlist_doc_ids=allowlist_doc_ids,
            ):
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
        db.query(DBDocument.id, DBDocument.dataset_id, DBDocument.access_mode, DBDocument.owner_id, DBDocument.updated_at)
        .filter(DBDocument.tenant_id == tenant_id)
    )
    query = query.filter(DBDocument.publication_status == "published")
    if status:
        if str(status).lower() == "completed":
            # Versioning: allow documents that are currently reprocessing/failed/cancelled,
            # as long as they still have an active pipeline that was completed before.
            query = query.filter(
                (DBDocument.status == "completed")
                | (DBDocument.doc_metadata["active_pipeline_ready"].astext == "true")  # type: ignore[attr-defined]
            )
        else:
            query = query.filter(DBDocument.status == status)

    query = query.order_by(DBDocument.updated_at.desc())
    if limit and limit > 0:
        query = query.limit(limit)

    documents = query.all()
    if not documents:
        return []

    dataset_ids = {dataset_id for _, dataset_id, *_ in documents if dataset_id}
    dataset_map, allowed_dataset_ids = _resolve_allowed_dataset_ids(db, tenant_id, account_id, dataset_ids)

    # Batch fetch allowlist membership for docs that require it.
    doc_ids_needing_allowlist: list[UUID] = []
    for doc_id, _dataset_id, access_mode, owner_id, _updated_at in documents:
        mode = _normalize_doc_access_mode(access_mode)
        if mode == _DOC_ACCESS_PARTIAL and (str(owner_id or "").strip() != account_id):
            doc_ids_needing_allowlist.append(doc_id)

    allowlist_doc_ids: Set[UUID] = set()
    if doc_ids_needing_allowlist:
        rows = (
            db.query(DocumentPermission.document_id)
            .filter(
                DocumentPermission.tenant_id == tenant_id,
                DocumentPermission.account_id == account_id,
                DocumentPermission.document_id.in_(doc_ids_needing_allowlist),
            )
            .all()
        )
        allowlist_doc_ids = {row[0] for row in rows if row and row[0]}
        group_ids = _resolve_account_group_ids(db, tenant_id=tenant_id, account_id=account_id)
        if group_ids:
            rows = (
                db.query(DocumentGroupPermission.document_id)
                .filter(
                    DocumentGroupPermission.tenant_id == tenant_id,
                    DocumentGroupPermission.document_id.in_(doc_ids_needing_allowlist),
                    DocumentGroupPermission.group_id.in_(list(group_ids)),
                )
                .all()
            )
            allowlist_doc_ids.update({row[0] for row in rows if row and row[0]})

    accessible: List[UUID] = []
    for doc_id, dataset_id, access_mode, owner_id, _ in documents:
        if not dataset_id:
            if _doc_access_allows(
                doc_id=doc_id,
                access_mode=access_mode,
                owner_id=owner_id,
                account_id=account_id,
                allowlist_doc_ids=allowlist_doc_ids,
            ):
                accessible.append(doc_id)
            continue
        if dataset_id not in dataset_map:
            continue
        if dataset_id in allowed_dataset_ids:
            ds = dataset_map.get(dataset_id)
            if ds is not None and str(getattr(ds, "owner_id", "") or "") == account_id:
                accessible.append(doc_id)
                continue
            if _doc_access_allows(
                doc_id=doc_id,
                access_mode=access_mode,
                owner_id=owner_id,
                account_id=account_id,
                allowlist_doc_ids=allowlist_doc_ids,
            ):
                accessible.append(doc_id)
    return accessible
