
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.core.constants import UserRoles
from app.models.dataset import Dataset
from app.models.document import Document as DBDocument
from app.models.document import DocumentPermission
from app.services.dataset_service import EDIT_ROLES, DatasetService
from app.services.document_permission_service import DocumentGroupPermissionService
from app.services.tenant_group_service import TenantGroupService

NO_DOCUMENT_ACCESS_DETAIL = "No document access"
NO_UNASSIGNED_DOCUMENT_WRITE_DETAIL = "No permission to manage unassigned documents"


def _raise_no_document_access() -> None:
    raise HTTPException(status_code=403, detail=NO_DOCUMENT_ACCESS_DETAIL)


def _document_acl_owner_allowed(*, account_id: str, document: DBDocument, dataset: Dataset | None) -> bool:
    if dataset is not None and str(getattr(dataset, "owner_id", "") or "") == account_id:
        return True
    owner_id = (str(getattr(document, "owner_id", "") or "")).strip()
    return bool(owner_id and owner_id == account_id)


def _document_acl_inherited_allowed(*, dataset: Dataset | None) -> bool:
    return dataset is not None


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

    group_ids = TenantGroupService.resolve_account_group_ids(db, tenant_id=tenant_id, account_id=account_id)
    if not group_ids:
        return False
    allowlist_groups = DocumentGroupPermissionService.get_document_partial_group_list(
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

    mode = (str(getattr(document, "access_mode", "") or "")).strip().lower()
    if _document_acl_owner_allowed(account_id=account_id, document=document, dataset=dataset):
        return

    if mode == "all_team_members":
        return

    if not mode or mode == "inherit":
        if _document_acl_inherited_allowed(dataset=dataset):
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
    return (
        db.query(DBDocument)
        .filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id)
        .first()
    )


def assert_document_readable_for_lifecycle(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    document: DBDocument,
) -> None:
    dataset: Dataset | None = None
    if getattr(document, "dataset_id", None):
        dataset = DatasetService.get_dataset(db, tenant_id, document.dataset_id)
        DatasetService.assert_dataset_readable(db, dataset, account_id)

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
    member = DatasetService.ensure_member(db, tenant_id, account_id)
    role = (getattr(member, "role", None) or "").lower()
    if role in UserRoles.ADMIN_ROLES:
        return
    if role not in EDIT_ROLES:
        raise HTTPException(status_code=403, detail=NO_UNASSIGNED_DOCUMENT_WRITE_DETAIL)

    owner_id = (str(getattr(document, "owner_id", "") or "")).strip()
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
    if getattr(document, "dataset_id", None):
        dataset = DatasetService.get_dataset(db, tenant_id, document.dataset_id)
        DatasetService.assert_dataset_writable(db, dataset, account_id)
        return

    assert_document_writable_for_unassigned_target(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        document=document,
    )


def assert_document_writable_for_lifecycle(
    db: Session,
    *,
    tenant_id: UUID,
    account_id: str,
    document: DBDocument,
) -> None:
    dataset: Dataset | None = None
    if getattr(document, "dataset_id", None):
        dataset = DatasetService.get_dataset(db, tenant_id, document.dataset_id)
        DatasetService.assert_dataset_writable(db, dataset, account_id)
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
