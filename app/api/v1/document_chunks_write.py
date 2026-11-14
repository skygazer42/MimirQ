from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_account_id, get_tenant_id
from app.api.schemas.documents import (
    DocumentChunkCreateRequest,
    DocumentChunkReembedRequest,
    DocumentChunkReembedResponse,
    DocumentChunkSchema,
    DocumentChunkUpdateRequest,
)
from app.api.utils import DEFAULT_HTTP_EXCEPTION_RESPONSES
from app.core.database import get_db
from app.models.document import DocumentChunk
from app.services import document_chunk_operations

router = APIRouter(responses=DEFAULT_HTTP_EXCEPTION_RESPONSES)


@router.post("/{document_id}/chunks", response_model=DocumentChunkSchema, status_code=201)
def create_document_chunk(
    document_id: UUID,
    payload: DocumentChunkCreateRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> DocumentChunk:
    return document_chunk_operations.create_chunk(
        document_id=document_id,
        payload=payload,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )


@router.patch("/{document_id}/chunks/{chunk_id}", response_model=DocumentChunkSchema)
def patch_document_chunk(
    document_id: UUID,
    chunk_id: UUID,
    payload: DocumentChunkUpdateRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> DocumentChunk:
    return document_chunk_operations.patch_chunk(
        document_id=document_id,
        chunk_id=chunk_id,
        payload=payload,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )


@router.delete("/{document_id}/chunks/{chunk_id}", status_code=204)
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


@router.post("/{document_id}/chunks/{chunk_id}/disable", response_model=DocumentChunkSchema)
async def disable_document_chunk(
    document_id: UUID,
    chunk_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> DocumentChunk:
    return await document_chunk_operations.disable_chunk(
        document_id=document_id,
        chunk_id=chunk_id,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )


@router.post("/{document_id}/chunks/{chunk_id}/enable", response_model=DocumentChunkSchema)
def enable_document_chunk(
    document_id: UUID,
    chunk_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> DocumentChunk:
    return document_chunk_operations.enable_chunk(
        document_id=document_id,
        chunk_id=chunk_id,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )


@router.post("/{document_id}/chunks/reembed", response_model=DocumentChunkReembedResponse)
def reembed_document_chunks(
    document_id: UUID,
    payload: DocumentChunkReembedRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> DocumentChunkReembedResponse:
    result = document_chunk_operations.reembed_chunks(
        document_id=document_id,
        payload=payload,
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )
    return DocumentChunkReembedResponse.model_validate(result)
