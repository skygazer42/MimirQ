
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.dataset import Dataset
from app.models.document import Document as DBDocument
from app.models.document import DocumentPermission
from app.services.dataset_service import EDIT_ROLES, DatasetService
from app.services.document_permission_service import DocumentGroupPermissionService
from app.services.tenant_group_service import TenantGroupService

NO_DOCUMENT_ACCESS_DETAIL = "No document access"


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
    """
    if not account_id:
        return

    if dataset is not None and str(getattr(dataset, "owner_id", "") or "") == account_id:
        return

    mode = (str(getattr(document, "access_mode", "") or "")).strip().lower()
    if not mode or mode in {"inherit", "all_team_members"}:
        return

    owner_id = (str(getattr(document, "owner_id", "") or "")).strip()
    if owner_id and owner_id == account_id:
        return

    if mode == "only_me":
        raise HTTPException(status_code=403, detail=NO_DOCUMENT_ACCESS_DETAIL)

    if mode == "partial_members":
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
            return

        group_ids = TenantGroupService.resolve_account_group_ids(db, tenant_id=tenant_id, account_id=account_id)
        if group_ids:
            allowlist_groups = DocumentGroupPermissionService.get_document_partial_group_list(
                db,
                tenant_id,
                document.id,
            )
            if allowlist_groups:
                allowed = set(allowlist_groups)
                if any(group_id in allowed for group_id in group_ids):
                    return

        raise HTTPException(status_code=403, detail=NO_DOCUMENT_ACCESS_DETAIL)

    raise HTTPException(status_code=403, detail=NO_DOCUMENT_ACCESS_DETAIL)


def get_document_for_lifecycle(db: Session, tenant_id: UUID, document_id: UUID) -> DBDocument | None:
    return (
        db.query(DBDocument)
        .filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id)
        .first()
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
    else:
        member = DatasetService.ensure_member(db, tenant_id, account_id)
        role = (getattr(member, "role", None) or "").lower()
        if role not in EDIT_ROLES:
            raise HTTPException(status_code=403, detail="No permission to manage unassigned documents")

    assert_document_acl_readable(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        document=document,
        dataset=dataset,
    )
