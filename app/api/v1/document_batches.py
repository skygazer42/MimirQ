from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.document import (
    DocumentBatchAccessUpdateRequest,
    DocumentBatchAccessUpdateResponse,
    DocumentBatchMoveRequest,
    DocumentBatchMoveResponse,
    DocumentBatchReingestRequest,
    DocumentBatchRetryRequest,
    DocumentBatchRetryResponse,
    DocumentBatchUserMetadataPatchRequest,
    DocumentBatchUserMetadataPatchResponse,
)
from app.core.database import get_db
from app.services import document_batch_operations

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

_record_batch_http_error = document_batch_operations._record_batch_http_error
_resolve_batch_move_target = document_batch_operations._resolve_batch_move_target
_move_document_conflicts = document_batch_operations._move_document_conflicts

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)


@router.post(
    "/batch/metadata",
    response_model=DocumentBatchUserMetadataPatchResponse,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def batch_patch_document_user_metadata(
    payload: DocumentBatchUserMetadataPatchRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> DocumentBatchUserMetadataPatchResponse:
    return document_batch_operations.patch_user_metadata(
        payload=payload,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )


@router.post("/batch/retry", response_model=DocumentBatchRetryResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def batch_retry_documents(
    payload: DocumentBatchRetryRequest,
    background_tasks: BackgroundTasks,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> DocumentBatchRetryResponse:
    return await document_batch_operations.retry_documents(
        payload=payload,
        background_tasks=background_tasks,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )


@router.post("/batch/reingest", response_model=DocumentBatchRetryResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def batch_reingest_documents(
    payload: DocumentBatchReingestRequest,
    background_tasks: BackgroundTasks,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> DocumentBatchRetryResponse:
    return await document_batch_operations.reingest_documents(
        payload=payload,
        background_tasks=background_tasks,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )


@router.post(
    "/batch/access",
    response_model=DocumentBatchAccessUpdateResponse,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
async def batch_update_document_access(
    payload: DocumentBatchAccessUpdateRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> DocumentBatchAccessUpdateResponse:
    return document_batch_operations.update_document_access(
        payload=payload,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )


@router.post("/batch/move", response_model=DocumentBatchMoveResponse, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def batch_move_documents(
    payload: DocumentBatchMoveRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> DocumentBatchMoveResponse:
    return document_batch_operations.move_documents(
        payload=payload,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )
