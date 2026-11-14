from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_account_id, get_tenant_id
from app.api.schemas.documents import DocumentRetryQuery, DocumentStatus
from app.api.utils import DEFAULT_HTTP_EXCEPTION_RESPONSES
from app.core.database import get_db
from app.services import document_lifecycle_service, document_processing_operations

router = APIRouter(responses=DEFAULT_HTTP_EXCEPTION_RESPONSES)


@router.get("/{document_id}/status", response_model=DocumentStatus)
def get_document_status(
    document_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> DocumentStatus:
    return document_processing_operations.read_document_status(
        document_id=document_id,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )


@router.post("/{document_id}/cancel", response_model=DocumentStatus)
async def cancel_document_processing(
    document_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> DocumentStatus:
    return await document_processing_operations.cancel_document(
        document_id=document_id,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )


@router.post("/{document_id}/retry", response_model=DocumentStatus)
async def retry_document_processing(
    document_id: UUID,
    background_tasks: BackgroundTasks,
    params: Annotated[DocumentRetryQuery, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> DocumentStatus:
    return await document_processing_operations.retry_document(
        document_id=document_id,
        background_tasks=background_tasks,
        force=params.force,
        skip_if_unchanged=params.skip_if_unchanged,
        parser_backend=params.parser_backend,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )


@router.delete("/{document_id}", status_code=204)
async def delete_document(
    document_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> None:
    await document_lifecycle_service._delete_document_lifecycle(
        document_id=document_id,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
        enforce_permissions=True,
    )
