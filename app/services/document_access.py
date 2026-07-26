from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import and_, exists, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import ColumnElement

from app.models.dataset import Dataset, DatasetPermission, DatasetPermissionEnum
from app.models.document import Document as DBDocument
from app.models.document import DocumentPermission
from app.models.group_permissions import DatasetGroupPermission, DocumentGroupPermission
from app.models.tenant_group import TenantGroupMember
from app.services.authz_prometheus_metrics import observe_group_permission_check
from app.services.dataset_service import DatasetService
from app.services.tenant_group_service import TenantGroupService

# Document-level ACL ("security trimming") modes.
_DOC_ACCESS_DEFAULTS = {"", "inherit"}
_DOC_ACCESS_ALL = "all_team_members"
_DOC_ACCESS_OWNER_ONLY = "only_me"
_DOC_ACCESS_PARTIAL = "partial_members"


def _resolve_account_group_ids(db: Session, *, tenant_id: UUID, account_id: str) -> set[UUID]:
    """
    Resolve tenant-scoped group ids for an account.

    Note: this is a low-level helper used by permission checks; it must not raise
    for missing memberships (empty set means "no groups").
    """
    return TenantGroupService.resolve_account_group_ids(db, tenant_id=tenant_id, account_id=account_id)


def build_dataset_read_filter(*, tenant_id: UUID, account_id: str) -> ColumnElement[bool]:
    """Build the tenant-scoped dataset read predicate used by list-style queries."""
    member_group_ids = select(TenantGroupMember.group_id).where(
        TenantGroupMember.tenant_id == tenant_id,
        TenantGroupMember.user_id == account_id,
    )
    member_allowed = exists().where(
        DatasetPermission.tenant_id == tenant_id,
        DatasetPermission.dataset_id == Dataset.id,
        DatasetPermission.account_id == account_id,
    )
    group_allowed = exists().where(
        DatasetGroupPermission.tenant_id == tenant_id,
        DatasetGroupPermission.dataset_id == Dataset.id,
        DatasetGroupPermission.group_id.in_(member_group_ids),
    )
    return or_(
        Dataset.owner_id == account_id,
        Dataset.permission == DatasetPermissionEnum.ALL_TEAM_MEMBERS,
        and_(
            Dataset.permission == DatasetPermissionEnum.PARTIAL_MEMBERS,
            or_(member_allowed, group_allowed),
        ),
    )


def build_document_read_filter(
    *,
    tenant_id: UUID,
    account_id: str,
    document_model: type[DBDocument] = DBDocument,
) -> ColumnElement[bool]:
    """Build document security trimming, including direct and group allowlists."""
    member_group_ids = select(TenantGroupMember.group_id).where(
        TenantGroupMember.tenant_id == tenant_id,
        TenantGroupMember.user_id == account_id,
    )
    member_allowed = exists().where(
        DocumentPermission.tenant_id == tenant_id,
        DocumentPermission.document_id == document_model.id,
        DocumentPermission.account_id == account_id,
    )
    group_allowed = exists().where(
        DocumentGroupPermission.tenant_id == tenant_id,
        DocumentGroupPermission.document_id == document_model.id,
        DocumentGroupPermission.group_id.in_(member_group_ids),
    )
    owner_dataset_ids = select(Dataset.id).where(
        Dataset.tenant_id == tenant_id,
        Dataset.owner_id == account_id,
    )
    return or_(
        document_model.dataset_id.in_(owner_dataset_ids),
        and_(
            document_model.dataset_id.isnot(None),
            or_(document_model.access_mode.is_(None), document_model.access_mode == "inherit"),
        ),
        document_model.access_mode == _DOC_ACCESS_ALL,
        document_model.owner_id == account_id,
        and_(
            document_model.access_mode == _DOC_ACCESS_PARTIAL,
            or_(member_allowed, group_allowed),
        ),
    )


def _normalize_doc_access_mode(value: object) -> str:
    return (str(value or "")).strip().lower()


def _doc_access_allows(
    *,
    doc_id: UUID,
    access_mode: object,
    owner_id: object,
    account_id: str,
    allowlist_doc_ids: set[UUID],
    has_dataset: bool,
) -> bool:
    """
    Evaluate document-level ACL for a single doc.

    Notes:
    - Dataset-level permissions are enforced separately; this only checks document overrides.
    - Unknown modes fail closed for defense-in-depth.
    """
    mode = _normalize_doc_access_mode(access_mode)
    owner = (str(owner_id or "")).strip()

    if mode in _DOC_ACCESS_DEFAULTS:
        return has_dataset or bool(owner and owner == account_id)

    if mode == _DOC_ACCESS_ALL:
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
    dataset_ids: set[UUID],
) -> tuple[dict[UUID, Dataset], set[UUID]]:
    if not dataset_ids:
        return {}, set()

    datasets = db.query(Dataset).filter(Dataset.tenant_id == tenant_id, Dataset.id.in_(list(dataset_ids))).all()
    dataset_map = {ds.id: ds for ds in datasets}

    allowed_dataset_ids: set[UUID] = set()
    partial_dataset_ids: set[UUID] = set()
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
        member_allowed_dataset_ids = {row[0] for row in rows if row and row[0]}
        allowed_dataset_ids.update(member_allowed_dataset_ids)

        group_ids = _resolve_account_group_ids(db, tenant_id=tenant_id, account_id=account_id)
        group_allowed_dataset_ids: set[UUID] = set()
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
            group_allowed_dataset_ids = {row[0] for row in rows if row and row[0]}
            allowed_dataset_ids.update(group_allowed_dataset_ids)

        # Group permission checks are a fallback after explicit (member) allowlists.
        for ds_id in partial_dataset_ids - member_allowed_dataset_ids:
            if not group_ids:
                observe_group_permission_check(resource="dataset", action="read", result="deny_no_groups")
            elif ds_id in group_allowed_dataset_ids:
                observe_group_permission_check(resource="dataset", action="read", result="allow")
            else:
                observe_group_permission_check(resource="dataset", action="read", result="deny_no_match")

    return dataset_map, allowed_dataset_ids


def get_readable_datasets_map(
    db: Session,
    tenant_id: UUID,
    account_id: str,
    dataset_ids: list[UUID] | None,
    *,
    check_member: bool = True,
) -> dict[UUID, Dataset]:
    requested_ids = list(dict.fromkeys(dataset_ids or []))
    if check_member:
        DatasetService.ensure_member(db, tenant_id, account_id)
    if not requested_ids:
        return {}

    dataset_map, allowed_dataset_ids = _resolve_allowed_dataset_ids(db, tenant_id, account_id, set(requested_ids))

    missing_ids = [dataset_id for dataset_id in requested_ids if dataset_id not in dataset_map]
    if missing_ids:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")

    blocked_ids = [dataset_id for dataset_id in requested_ids if dataset_id not in allowed_dataset_ids]
    if blocked_ids:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="No dataset access")

    return {dataset_id: dataset_map[dataset_id] for dataset_id in requested_ids}


def get_allowed_document_id_sets(
    db: Session,
    tenant_id: UUID,
    account_id: str,
    doc_ids: list[UUID] | None,
    *,
    check_member: bool = True,
    _check_member: bool | None = None,
) -> tuple[set[UUID], set[UUID]]:
    """
    Resolve (allowed_ids, missing_ids) for a set of document IDs.

    - missing_ids: document ids not found under the tenant
    - allowed_ids: ids the account can read; unbound documents require an explicit ACL or ownership
    """
    check_member0 = bool(_check_member) if _check_member is not None else bool(check_member)
    if check_member0:
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

    allowlist_doc_ids: set[UUID] = set()
    member_allowlist_doc_ids: set[UUID] = set()
    group_allowlist_doc_ids: set[UUID] = set()
    allowlist_group_ids: set[UUID] = set()
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
        member_allowlist_doc_ids = {row[0] for row in rows if row and row[0]}
        allowlist_group_ids = _resolve_account_group_ids(db, tenant_id=tenant_id, account_id=account_id)
        if allowlist_group_ids:
            rows = (
                db.query(DocumentGroupPermission.document_id)
                .filter(
                    DocumentGroupPermission.tenant_id == tenant_id,
                    DocumentGroupPermission.document_id.in_(doc_ids_needing_allowlist),
                    DocumentGroupPermission.group_id.in_(list(allowlist_group_ids)),
                )
                .all()
            )
            group_allowlist_doc_ids = {row[0] for row in rows if row and row[0]}
        allowlist_doc_ids = member_allowlist_doc_ids | group_allowlist_doc_ids

    allowed_ids: set[UUID] = set()
    for doc_id, dataset_id, access_mode, owner_id in documents:
        if not dataset_id:
            # No dataset ACL exists to inherit, so default/inherit access fails closed for non-owners.
            mode = _normalize_doc_access_mode(access_mode)
            if (
                mode == _DOC_ACCESS_PARTIAL
                and (str(owner_id or "").strip() != account_id)
                and doc_id not in member_allowlist_doc_ids
            ):
                if not allowlist_group_ids:
                    observe_group_permission_check(resource="document", action="read", result="deny_no_groups")
                elif doc_id in group_allowlist_doc_ids:
                    observe_group_permission_check(resource="document", action="read", result="allow")
                else:
                    observe_group_permission_check(resource="document", action="read", result="deny_no_match")
            if _doc_access_allows(
                doc_id=doc_id,
                access_mode=access_mode,
                owner_id=owner_id,
                account_id=account_id,
                allowlist_doc_ids=allowlist_doc_ids,
                has_dataset=False,
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
            mode = _normalize_doc_access_mode(access_mode)
            if (
                mode == _DOC_ACCESS_PARTIAL
                and (str(owner_id or "").strip() != account_id)
                and doc_id not in member_allowlist_doc_ids
            ):
                if not allowlist_group_ids:
                    observe_group_permission_check(resource="document", action="read", result="deny_no_groups")
                elif doc_id in group_allowlist_doc_ids:
                    observe_group_permission_check(resource="document", action="read", result="allow")
                else:
                    observe_group_permission_check(resource="document", action="read", result="deny_no_match")
            if _doc_access_allows(
                doc_id=doc_id,
                access_mode=access_mode,
                owner_id=owner_id,
                account_id=account_id,
                allowlist_doc_ids=allowlist_doc_ids,
                has_dataset=True,
            ):
                allowed_ids.add(doc_id)

    return allowed_ids, missing_ids


def filter_allowed_document_ids(
    db: Session,
    tenant_id: UUID,
    account_id: str,
    doc_ids: list[UUID] | None,
) -> list[UUID]:
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
    dataset_id: UUID | None = None,
    status: str | None = "completed",
    limit: int | None = 200,
) -> list[UUID]:
    """
    List accessible document IDs under a tenant for the current account.

    This is a batched/efficient variant for "default scope" scenarios (e.g. chat without explicit document_ids).
    It enforces dataset permissions without issuing 1 query per document.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)
    query = db.query(
        DBDocument.id, DBDocument.dataset_id, DBDocument.access_mode, DBDocument.owner_id, DBDocument.updated_at
    ).filter(DBDocument.tenant_id == tenant_id)
    query = query.filter(DBDocument.publication_status == "published")
    if dataset_id is not None:
        query = query.filter(DBDocument.dataset_id == dataset_id)
    if status:
        if str(status).lower() == "completed":
            # Versioning: allow documents that are currently reprocessing/failed/cancelled,
            # as long as they still have an active pipeline that was completed before.
            query = query.filter(
                (DBDocument.status == "completed") | (DBDocument.doc_metadata["active_pipeline_ready"].astext == "true")  # type: ignore[attr-defined]
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

    allowlist_doc_ids: set[UUID] = set()
    member_allowlist_doc_ids: set[UUID] = set()
    group_allowlist_doc_ids: set[UUID] = set()
    allowlist_group_ids: set[UUID] = set()
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
        member_allowlist_doc_ids = {row[0] for row in rows if row and row[0]}
        allowlist_group_ids = _resolve_account_group_ids(db, tenant_id=tenant_id, account_id=account_id)
        if allowlist_group_ids:
            rows = (
                db.query(DocumentGroupPermission.document_id)
                .filter(
                    DocumentGroupPermission.tenant_id == tenant_id,
                    DocumentGroupPermission.document_id.in_(doc_ids_needing_allowlist),
                    DocumentGroupPermission.group_id.in_(list(allowlist_group_ids)),
                )
                .all()
            )
            group_allowlist_doc_ids = {row[0] for row in rows if row and row[0]}
        allowlist_doc_ids = member_allowlist_doc_ids | group_allowlist_doc_ids

    accessible: list[UUID] = []
    for doc_id, dataset_id, access_mode, owner_id, _ in documents:
        if not dataset_id:
            mode = _normalize_doc_access_mode(access_mode)
            if (
                mode == _DOC_ACCESS_PARTIAL
                and (str(owner_id or "").strip() != account_id)
                and doc_id not in member_allowlist_doc_ids
            ):
                if not allowlist_group_ids:
                    observe_group_permission_check(resource="document", action="read", result="deny_no_groups")
                elif doc_id in group_allowlist_doc_ids:
                    observe_group_permission_check(resource="document", action="read", result="allow")
                else:
                    observe_group_permission_check(resource="document", action="read", result="deny_no_match")
            if _doc_access_allows(
                doc_id=doc_id,
                access_mode=access_mode,
                owner_id=owner_id,
                account_id=account_id,
                allowlist_doc_ids=allowlist_doc_ids,
                has_dataset=False,
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
            mode = _normalize_doc_access_mode(access_mode)
            if (
                mode == _DOC_ACCESS_PARTIAL
                and (str(owner_id or "").strip() != account_id)
                and doc_id not in member_allowlist_doc_ids
            ):
                if not allowlist_group_ids:
                    observe_group_permission_check(resource="document", action="read", result="deny_no_groups")
                elif doc_id in group_allowlist_doc_ids:
                    observe_group_permission_check(resource="document", action="read", result="allow")
                else:
                    observe_group_permission_check(resource="document", action="read", result="deny_no_match")
            if _doc_access_allows(
                doc_id=doc_id,
                access_mode=access_mode,
                owner_id=owner_id,
                account_id=account_id,
                allowlist_doc_ids=allowlist_doc_ids,
                has_dataset=True,
            ):
                accessible.append(doc_id)
    return accessible
