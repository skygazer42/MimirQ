from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.document import (
    DocumentBatchDeleteRequest,
    DocumentBatchDeleteResponse,
    DocumentBatchLifecycleRequest,
    DocumentBatchLifecycleResponse,
)
from app.core.database import get_db
from app.services import document_lifecycle_service

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}
_update_document_lifecycle_state = document_lifecycle_service.update_document_lifecycle_state
router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)


@router.post(
    "/batch/disable",
    response_model=DocumentBatchLifecycleResponse,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def batch_disable_documents(
    payload: DocumentBatchLifecycleRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, int | list[UUID]]:
    return _update_document_lifecycle_state(
        payload,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
        state_field="disabled_at",
        audit_action="document.disable",
        set_timestamp=True,
    )


@router.post(
    "/batch/enable",
    response_model=DocumentBatchLifecycleResponse,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def batch_enable_documents(
    payload: DocumentBatchLifecycleRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, int | list[UUID]]:
    return _update_document_lifecycle_state(
        payload,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
        state_field="disabled_at",
        audit_action="document.enable",
        set_timestamp=False,
    )


@router.post(
    "/batch/archive",
    response_model=DocumentBatchLifecycleResponse,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def batch_archive_documents(
    payload: DocumentBatchLifecycleRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, int | list[UUID]]:
    return _update_document_lifecycle_state(
        payload,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
        state_field="archived_at",
        audit_action="document.archive",
        set_timestamp=True,
    )


@router.post(
    "/batch/unarchive",
    response_model=DocumentBatchLifecycleResponse,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def batch_unarchive_documents(
    payload: DocumentBatchLifecycleRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, int | list[UUID]]:
    return _update_document_lifecycle_state(
        payload,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
        state_field="archived_at",
        audit_action="document.unarchive",
        set_timestamp=False,
    )


@router.post(
    "/batch-delete",
    response_model=DocumentBatchDeleteResponse,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
async def batch_delete_documents(
    payload: DocumentBatchDeleteRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, int | list[UUID]]:
    return await document_lifecycle_service.delete_documents(
        payload,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )
