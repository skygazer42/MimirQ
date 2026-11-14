from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_account_id, get_tenant_id
from app.api.schemas.documents import (
    DocumentBatchDeleteRequest,
    DocumentBatchDeleteResponse,
    DocumentBatchLifecycleRequest,
    DocumentBatchLifecycleResponse,
)
from app.api.utils import DEFAULT_HTTP_EXCEPTION_RESPONSES
from app.core.database import get_db
from app.services import document_lifecycle_service

router = APIRouter(responses=DEFAULT_HTTP_EXCEPTION_RESPONSES)


@router.post("/batch/disable", response_model=DocumentBatchLifecycleResponse)
def batch_disable_documents(
    payload: DocumentBatchLifecycleRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> DocumentBatchLifecycleResponse:
    result = document_lifecycle_service.update_document_lifecycle_state(
        payload,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
        state_field="disabled_at",
        audit_action="document.disable",
        set_timestamp=True,
    )
    return DocumentBatchLifecycleResponse.model_validate(result)


@router.post("/batch/enable", response_model=DocumentBatchLifecycleResponse)
def batch_enable_documents(
    payload: DocumentBatchLifecycleRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> DocumentBatchLifecycleResponse:
    result = document_lifecycle_service.update_document_lifecycle_state(
        payload,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
        state_field="disabled_at",
        audit_action="document.enable",
        set_timestamp=False,
    )
    return DocumentBatchLifecycleResponse.model_validate(result)


@router.post("/batch/archive", response_model=DocumentBatchLifecycleResponse)
def batch_archive_documents(
    payload: DocumentBatchLifecycleRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> DocumentBatchLifecycleResponse:
    result = document_lifecycle_service.update_document_lifecycle_state(
        payload,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
        state_field="archived_at",
        audit_action="document.archive",
        set_timestamp=True,
    )
    return DocumentBatchLifecycleResponse.model_validate(result)


@router.post("/batch/unarchive", response_model=DocumentBatchLifecycleResponse)
def batch_unarchive_documents(
    payload: DocumentBatchLifecycleRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> DocumentBatchLifecycleResponse:
    result = document_lifecycle_service.update_document_lifecycle_state(
        payload,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
        state_field="archived_at",
        audit_action="document.unarchive",
        set_timestamp=False,
    )
    return DocumentBatchLifecycleResponse.model_validate(result)


@router.post("/batch-delete", response_model=DocumentBatchDeleteResponse)
async def batch_delete_documents(
    payload: DocumentBatchDeleteRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> DocumentBatchDeleteResponse:
    result = await document_lifecycle_service.delete_documents(
        payload,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )
    return DocumentBatchDeleteResponse.model_validate(result)
