from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.document import (
    DocumentChunkCreateRequest,
    DocumentChunkReembedRequest,
    DocumentChunkReembedResponse,
    DocumentChunkSchema,
    DocumentChunkUpdateRequest,
)
from app.core.database import get_db
from app.models.document import DocumentChunk as DBDocumentChunk
from app.services import document_chunk_operations

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

CHUNK_NOT_FOUND_DETAIL = document_chunk_operations.CHUNK_NOT_FOUND_DETAIL
CHUNK_NOT_ACTIVE_PIPELINE_DETAIL = document_chunk_operations.CHUNK_NOT_ACTIVE_PIPELINE_DETAIL
CHUNK_PATCH_OPERATION = document_chunk_operations.CHUNK_PATCH_OPERATION

_get_document_for_chunk_ops = document_chunk_operations._get_document_for_chunk_ops
_get_chunk_for_chunk_ops = document_chunk_operations._get_chunk_for_chunk_ops
_assert_document_writable_for_chunk_ops = document_chunk_operations._assert_document_writable_for_chunk_ops
_resolve_active_doc_pipeline_key = document_chunk_operations._resolve_active_doc_pipeline_key
_normalize_index_consistency_strictness = document_chunk_operations._normalize_index_consistency_strictness
_build_index_channel_result = document_chunk_operations._build_index_channel_result
_index_channel_status = document_chunk_operations._index_channel_status
_index_drift_marker_rows = document_chunk_operations._index_drift_marker_rows
_build_chunk_index_operation_result = document_chunk_operations._build_chunk_index_operation_result
_persist_chunk_index_operation_result = document_chunk_operations._persist_chunk_index_operation_result
_enqueue_index_drift_reconcile = document_chunk_operations._enqueue_index_drift_reconcile
_build_chunk_drift_markers = document_chunk_operations._build_chunk_drift_markers
_record_chunk_index_drift = document_chunk_operations._record_chunk_index_drift

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)


@router.post(
    "/{document_id}/chunks",
    response_model=DocumentChunkSchema,
    status_code=201,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def create_document_chunk(
    document_id: UUID,
    payload: DocumentChunkCreateRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> DBDocumentChunk:
    return document_chunk_operations.create_chunk(
        document_id=document_id,
        payload=payload,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )


@router.patch(
    "/{document_id}/chunks/{chunk_id}",
    response_model=DocumentChunkSchema,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def patch_document_chunk(
    document_id: UUID,
    chunk_id: UUID,
    payload: DocumentChunkUpdateRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> DBDocumentChunk:
    return document_chunk_operations.patch_chunk(
        document_id=document_id,
        chunk_id=chunk_id,
        payload=payload,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )


@router.delete(
    "/{document_id}/chunks/{chunk_id}",
    status_code=204,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
async def delete_document_chunk(
    document_id: UUID,
    chunk_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> Response:
    await document_chunk_operations.delete_chunk(
        document_id=document_id,
        chunk_id=chunk_id,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )
    return Response(status_code=204)


@router.post(
    "/{document_id}/chunks/{chunk_id}/disable",
    response_model=DocumentChunkSchema,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
async def disable_document_chunk(
    document_id: UUID,
    chunk_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> DBDocumentChunk:
    return await document_chunk_operations.disable_chunk(
        document_id=document_id,
        chunk_id=chunk_id,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )


@router.post(
    "/{document_id}/chunks/{chunk_id}/enable",
    response_model=DocumentChunkSchema,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def enable_document_chunk(
    document_id: UUID,
    chunk_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> DBDocumentChunk:
    return document_chunk_operations.enable_chunk(
        document_id=document_id,
        chunk_id=chunk_id,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )


@router.post(
    "/{document_id}/chunks/reembed",
    response_model=DocumentChunkReembedResponse,
    responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES,
)
def reembed_document_chunks(
    document_id: UUID,
    payload: DocumentChunkReembedRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> dict[str, Any]:
    return document_chunk_operations.reembed_chunks(
        document_id=document_id,
        payload=payload,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )
