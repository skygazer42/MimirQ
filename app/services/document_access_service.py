from typing import NoReturn
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.api.schemas.document import DocumentAccessInfo, DocumentAccessUpdateRequest
from app.core.constants import UserRoles
from app.models.dataset import Dataset
from app.models.document import Document as DBDocument
from app.models.document import DocumentPermission
from app.services import dataset_service, tenant_group_service
from app.services.audit_log_service import audit_log_event
from app.services.document_permission_service import (
    clear_partial_group_list,
    clear_partial_member_list,
    get_document_partial_group_list,
    get_document_partial_member_list,
    update_partial_group_list,
    update_partial_member_list,
)

DOC_NOT_FOUND_DETAIL = "Document not found"
NO_DOCUMENT_ACCESS_DETAIL = "No document access"
NO_UNASSIGNED_DOCUMENT_WRITE_DETAIL = "No permission to manage unassigned documents"


def _raise_no_document_access() -> NoReturn:
    raise HTTPException(status_code=403, detail=NO_DOCUMENT_ACCESS_DETAIL)


def _document_acl_owner_allowed(*, account_id: str, document: DBDocument, dataset: Dataset | None) -> bool:
    if dataset is not None and (dataset.owner_id or "") == account_id:
        return True
    owner_id = (document.owner_id or "").strip()
    return bool(owner_id and owner_id == account_id)


def _document_acl_partial_member_allowed(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    document: DBDocument,
) -> bool:
    exists = (
        db.query(DocumentPermission)
        .filter(
            DocumentPermission.tenant_id == tenant_id,
            DocumentPermission.document_id == document.id,
            DocumentPermission.account_id == account_id,
        )
        .first()
    )
    if exists:
        return True

    group_ids = tenant_group_service.resolve_account_group_ids(db, tenant_id=tenant_id, account_id=account_id)
    if not group_ids:
        return False
    allowlist_groups = get_document_partial_group_list(
        db,
        tenant_id,
        document.id,
    )
    if not allowlist_groups:
        return False
    allowed = set(allowlist_groups)
    return any(group_id in allowed for group_id in group_ids)


def assert_document_acl_readable(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    document: DBDocument,
    dataset: Dataset | None = None,
) -> None:
    """
    Enforce document-level ACL ("security trimming") in addition to dataset permission.

    - Dataset permission is enforced by callers (or passed in via `dataset`).
    - Dataset owners can always access documents in their dataset.
    - Without a dataset, default/inherit access is owner-only because no parent ACL exists.
    """
    if not account_id:
        return

    mode = (document.access_mode or "").strip().lower()
    if _document_acl_owner_allowed(account_id=account_id, document=document, dataset=dataset):
        return

    if mode == "all_team_members":
        return

    if not mode or mode == "inherit":
        if dataset is not None:
            return
        _raise_no_document_access()

    if mode == "only_me":
        _raise_no_document_access()

    if mode == "partial_members" and _document_acl_partial_member_allowed(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        document=document,
    ):
        return

    _raise_no_document_access()


def get_document_for_lifecycle(db: Session, tenant_id: UUID, document_id: UUID) -> DBDocument | None:
    return db.query(DBDocument).filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id).first()


def assert_document_readable_for_lifecycle(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    document: DBDocument,
) -> None:
    dataset: Dataset | None = None
    if document.dataset_id:
        dataset = dataset_service.get_dataset(db, tenant_id, document.dataset_id)
        dataset_service.assert_dataset_readable(db, dataset, account_id)

    assert_document_acl_readable(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        document=document,
        dataset=dataset,
    )


def assert_document_writable_for_unassigned_target(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    document: DBDocument,
) -> None:
    member = dataset_service.ensure_member(db, tenant_id, account_id)
    role = (member.role or "").lower()
    if role in UserRoles.ADMIN_ROLES:
        return
    if role not in UserRoles.EDIT_ROLES:
        raise HTTPException(status_code=403, detail=NO_UNASSIGNED_DOCUMENT_WRITE_DETAIL)

    owner_id = (document.owner_id or "").strip()
    if owner_id and owner_id == account_id:
        return

    raise HTTPException(status_code=403, detail=NO_UNASSIGNED_DOCUMENT_WRITE_DETAIL)


def assert_document_access_manageable(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    document: DBDocument,
) -> None:
    """Authorize ACL repair without requiring the current document ACL."""
    if document.dataset_id:
        dataset = dataset_service.get_dataset(db, tenant_id, document.dataset_id)
        dataset_service.assert_dataset_writable(db, dataset, account_id)
        return

    assert_document_writable_for_unassigned_target(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        document=document,
    )


def get_document_access(
    *,
    document_id: UUID,
    tenant_id: UUID,
    account_id: str,
    db: Session,
) -> DocumentAccessInfo:
    dataset_service.ensure_member(db, tenant_id, account_id)
    document = get_document_for_lifecycle(db, tenant_id, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail=DOC_NOT_FOUND_DETAIL)

    dataset: Dataset | None = None
    if document.dataset_id:
        dataset = dataset_service.get_dataset(db, tenant_id, document.dataset_id)
        dataset_service.assert_dataset_readable(db, dataset, account_id)
    assert_document_acl_readable(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        document=document,
        dataset=dataset,
    )

    mode = (document.access_mode or "").strip().lower() or "inherit"
    partial_members: list[str] | None = None
    partial_groups: list[UUID] | None = None
    if mode == "partial_members":
        partial_members = get_document_partial_member_list(db, tenant_id, document_id)
        partial_groups = get_document_partial_group_list(db, tenant_id, document_id)

    return DocumentAccessInfo(
        mode=mode,
        owner_id=document.owner_id or None,
        partial_member_list=partial_members,
        partial_group_list=partial_groups,
    )


def update_document_access(
    *,
    document_id: UUID,
    payload: DocumentAccessUpdateRequest,
    tenant_id: UUID,
    account_id: str,
    db: Session,
) -> DocumentAccessInfo:
    dataset_service.ensure_member(db, tenant_id, account_id)
    document = get_document_for_lifecycle(db, tenant_id, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail=DOC_NOT_FOUND_DETAIL)
    assert_document_access_manageable(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        document=document,
    )

    mode = payload.mode
    document.access_mode = None if mode == "inherit" else mode
    if not (document.owner_id or "").strip():
        document.owner_id = account_id

    if mode == "partial_members":
        update_partial_member_list(db, tenant_id, document_id, payload.partial_member_list or [])
        update_partial_group_list(db, tenant_id, document_id, payload.partial_group_list or [])
    else:
        clear_partial_member_list(db, tenant_id, document_id)
        clear_partial_group_list(db, tenant_id, document_id)

    db.commit()
    db.refresh(document)

    partial_members: list[str] | None = None
    partial_groups: list[UUID] | None = None
    if mode == "partial_members":
        partial_members = get_document_partial_member_list(db, tenant_id, document_id)
        partial_groups = get_document_partial_group_list(db, tenant_id, document_id)

    audit_log_event(
        db,
        tenant_id=tenant_id,
        actor_id=account_id,
        action="document.access.update",
        resource_type="document",
        resource_id=str(document_id),
        details={
            "mode": mode,
            "dataset_id": str(document.dataset_id) if document.dataset_id is not None else None,
            "partial_member_count": len(partial_members or []),
            "partial_group_count": len(partial_groups or []),
        },
    )
    try:
        db.commit()
    except Exception:
        db.rollback()

    return DocumentAccessInfo(
        mode=mode,
        owner_id=document.owner_id or None,
        partial_member_list=partial_members,
        partial_group_list=partial_groups,
    )


def assert_document_writable_for_lifecycle(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    document: DBDocument,
) -> None:
    dataset: Dataset | None = None
    if document.dataset_id:
        dataset = dataset_service.get_dataset(db, tenant_id, document.dataset_id)
        dataset_service.assert_dataset_writable(db, dataset, account_id)
        assert_document_acl_readable(
            db,
            tenant_id=tenant_id,
            account_id=account_id,
            document=document,
            dataset=dataset,
        )
        return

    assert_document_writable_for_unassigned_target(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        document=document,
    )
