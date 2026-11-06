from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.document import DocumentStatus
from app.core.database import get_db
from app.services import document_lifecycle_service, document_processing_operations

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)

_document_status_payload = document_processing_operations._document_status_payload
_ensure_retryable_document_state = document_processing_operations._ensure_retryable_document_state
_apply_retry_parser_backend_override = document_processing_operations._apply_retry_parser_backend_override
_retry_chunk_exists = document_processing_operations._retry_chunk_exists
_maybe_skip_unchanged_retry = document_processing_operations._maybe_skip_unchanged_retry
_prepare_retry_metadata = document_processing_operations._prepare_retry_metadata
_mark_retry_pending = document_processing_operations._mark_retry_pending
_resolve_retry_source = document_processing_operations.resolve_retry_source
_delete_document_lifecycle = document_lifecycle_service._delete_document_lifecycle


@router.get("/{document_id}/status", response_model=DocumentStatus, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
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


@router.post("/{document_id}/cancel", response_model=DocumentStatus, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
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


@router.post("/{document_id}/retry", response_model=DocumentStatus, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def retry_document_processing(
    document_id: UUID,
    background_tasks: BackgroundTasks,
    force: bool = False,
    skip_if_unchanged: bool = False,
    parser_backend: str | None = None,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> DocumentStatus:
    return await document_processing_operations.retry_document(
        document_id=document_id,
        background_tasks=background_tasks,
        force=force,
        skip_if_unchanged=skip_if_unchanged,
        parser_backend=parser_backend,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )


@router.delete("/{document_id}", status_code=204, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
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
