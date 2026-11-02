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
from app.services import dataset_service, document_permission_service
from app.services.audit_log_service import audit_log_event
from app.services.document_access_service import assert_document_access_manageable, assert_document_acl_readable

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
def get_document_access(
    document_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> DocumentAccessInfo:
    """Get document-level ACL settings (requires document read access)."""
    dataset_service.ensure_member(db, tenant_id, account_id)

    document = db.query(DBDocument).filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id).first()
    if not document:
        raise HTTPException(status_code=404, detail=DOC_NOT_FOUND_DETAIL)

    dataset: Dataset | None = None
    if document.dataset_id:
        dataset = dataset_service.get_dataset(db, tenant_id, document.dataset_id)
        dataset_service.assert_dataset_readable(db, dataset, account_id)
    assert_document_acl_readable(db, tenant_id=tenant_id, account_id=account_id, document=document, dataset=dataset)

    mode = (document.access_mode or "").strip().lower() or "inherit"
    allowlist: list[str] | None = None
    allowlist_groups: list[UUID] | None = None
    if mode == "partial_members":
        allowlist = document_permission_service.get_document_partial_member_list(db, tenant_id, document_id)
        allowlist_groups = document_permission_service.get_document_partial_group_list(db, tenant_id, document_id)

    return DocumentAccessInfo(
        mode=mode,  # type: ignore[arg-type]
        owner_id=(document.owner_id or None),
        partial_member_list=allowlist,
        partial_group_list=allowlist_groups,
    )


@router.put("/{document_id}/access", response_model=DocumentAccessInfo, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def put_document_access(
    document_id: UUID,
    payload: DocumentAccessUpdateRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> DocumentAccessInfo:
    """Update document ACL settings using dataset or unassigned-document ownership policy."""
    dataset_service.ensure_member(db, tenant_id, account_id)

    document = db.query(DBDocument).filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id).first()
    if not document:
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
        document_permission_service.update_partial_member_list(
            db,
            tenant_id,
            document_id,
            payload.partial_member_list or [],
        )
        document_permission_service.update_partial_group_list(
            db,
            tenant_id,
            document_id,
            payload.partial_group_list or [],
        )
    else:
        document_permission_service.clear_partial_member_list(db, tenant_id, document_id)
        document_permission_service.clear_partial_group_list(db, tenant_id, document_id)

    db.commit()
    db.refresh(document)

    allowlist: list[str] | None = None
    allowlist_groups: list[UUID] | None = None
    if mode == "partial_members":
        allowlist = document_permission_service.get_document_partial_member_list(db, tenant_id, document_id)
        allowlist_groups = document_permission_service.get_document_partial_group_list(db, tenant_id, document_id)

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
            "partial_member_count": len(allowlist or []),
            "partial_group_count": len(allowlist_groups or []),
        },
    )
    try:
        db.commit()
    except Exception:
        db.rollback()

    return DocumentAccessInfo(
        mode=mode,  # type: ignore[arg-type]
        owner_id=(document.owner_id or None),
        partial_member_list=allowlist,
        partial_group_list=allowlist_groups,
    )
