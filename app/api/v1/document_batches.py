from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_account_id, get_tenant_id
from app.api.schemas.documents import (
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
from app.api.utils import DEFAULT_HTTP_EXCEPTION_RESPONSES
from app.core.async_bridge import run_blocking_in_thread
from app.core.database import SessionLocal, get_db
from app.services import document_batch_operations

router = APIRouter(responses=DEFAULT_HTTP_EXCEPTION_RESPONSES)


@router.post("/batch/metadata", response_model=DocumentBatchUserMetadataPatchResponse)
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


@router.post("/batch/retry", response_model=DocumentBatchRetryResponse)
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


@router.post("/batch/reingest", response_model=DocumentBatchRetryResponse)
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


def _update_batch_access(
    *, payload: DocumentBatchAccessUpdateRequest, tenant_id: UUID, account_id: str
) -> DocumentBatchAccessUpdateResponse:
    with SessionLocal() as db:
        return document_batch_operations.update_document_access(
            payload=payload, tenant_id=tenant_id, account_id=account_id, db=db
        )


@router.post("/batch/access", response_model=DocumentBatchAccessUpdateResponse)
async def batch_update_document_access(
    payload: DocumentBatchAccessUpdateRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
) -> DocumentBatchAccessUpdateResponse:
    return await run_blocking_in_thread(
        _update_batch_access,
        payload=payload,
        tenant_id=tenant_id,
        account_id=account_id,
    )


@router.post("/batch/move", response_model=DocumentBatchMoveResponse)
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
