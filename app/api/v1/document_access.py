from __future__ import annotations

import uuid
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.document import DocumentAccessInfo, DocumentAccessUpdateRequest
from app.core.database import get_db
from app.models.dataset import Dataset
from app.models.document import Document as DBDocument
from app.services.audit_log_service import audit_log_event
from app.services.dataset_service import EDIT_ROLES, DatasetService
from app.services.document_access_service import assert_document_acl_readable
from app.services.document_permission_service import DocumentGroupPermissionService, DocumentPermissionService

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

DOC_NOT_FOUND_DETAIL = "Document not found"

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)


@router.get("/{document_id}/access", response_model=DocumentAccessInfo, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def get_document_access(
    document_id: uuid.UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Get document-level ACL settings (requires document read access)."""
    DatasetService.ensure_member(db, tenant_id, account_id)

    document = (
        db.query(DBDocument)
        .filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id)
        .first()
    )
    if not document:
        raise HTTPException(status_code=404, detail=DOC_NOT_FOUND_DETAIL)

    dataset: Dataset | None = None
    if document.dataset_id:
        dataset = DatasetService.get_dataset(db, tenant_id, document.dataset_id)
        DatasetService.assert_dataset_readable(db, dataset, account_id)
    assert_document_acl_readable(db, tenant_id=tenant_id, account_id=account_id, document=document, dataset=dataset)

    mode = (str(getattr(document, "access_mode", "") or "")).strip().lower() or "inherit"
    allowlist: list[str] | None = None
    allowlist_groups: list[UUID] | None = None
    if mode == "partial_members":
        allowlist = DocumentPermissionService.get_document_partial_member_list(db, tenant_id, document_id)
        allowlist_groups = DocumentGroupPermissionService.get_document_partial_group_list(db, tenant_id, document_id)

    return DocumentAccessInfo(
        mode=mode,  # type: ignore[arg-type]
        owner_id=(getattr(document, "owner_id", None) or None),
        partial_member_list=allowlist,
        partial_group_list=allowlist_groups,
    )


@router.put("/{document_id}/access", response_model=DocumentAccessInfo, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def put_document_access(
    document_id: uuid.UUID,
    payload: DocumentAccessUpdateRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """Update document-level ACL settings (requires dataset write or tenant edit role)."""
    member = DatasetService.ensure_member(db, tenant_id, account_id)

    document = (
        db.query(DBDocument)
        .filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id)
        .first()
    )
    if not document:
        raise HTTPException(status_code=404, detail=DOC_NOT_FOUND_DETAIL)

    if document.dataset_id:
        dataset = DatasetService.get_dataset(db, tenant_id, document.dataset_id)
        DatasetService.assert_dataset_writable(db, dataset, account_id)
    else:
        role = (getattr(member, "role", None) or "").lower()
        if role not in EDIT_ROLES:
            raise HTTPException(status_code=403, detail="No permission to manage document access")

    mode = str(payload.mode or "inherit").strip().lower()
    document.access_mode = None if mode == "inherit" else mode

    if not (getattr(document, "owner_id", None) or "").strip():
        document.owner_id = account_id

    if mode == "partial_members":
        DocumentPermissionService.update_partial_member_list(
            db,
            tenant_id,
            document_id,
            list(payload.partial_member_list or []),
        )
        DocumentGroupPermissionService.update_partial_group_list(
            db,
            tenant_id,
            document_id,
            list(payload.partial_group_list or []),
        )
    else:
        DocumentPermissionService.clear_partial_member_list(db, tenant_id, document_id)
        DocumentGroupPermissionService.clear_partial_group_list(db, tenant_id, document_id)

    db.commit()
    db.refresh(document)

    allowlist: list[str] | None = None
    allowlist_groups: list[UUID] | None = None
    if mode == "partial_members":
        allowlist = DocumentPermissionService.get_document_partial_member_list(db, tenant_id, document_id)
        allowlist_groups = DocumentGroupPermissionService.get_document_partial_group_list(db, tenant_id, document_id)

    audit_log_event(
        db,
        tenant_id=tenant_id,
        actor_id=account_id,
        action="document.access.update",
        resource_type="document",
        resource_id=str(document_id),
        details={
            "mode": mode,
            "dataset_id": str(getattr(document, "dataset_id", None) or "") or None,
            "partial_member_count": int(len(allowlist or [])),
            "partial_group_count": int(len(allowlist_groups or [])),
        },
    )
    try:
        db.commit()
    except Exception:
        db.rollback()

    return DocumentAccessInfo(
        mode=mode,  # type: ignore[arg-type]
        owner_id=(getattr(document, "owner_id", None) or None),
        partial_member_list=allowlist,
        partial_group_list=allowlist_groups,
    )
