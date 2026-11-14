from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Query as OrmQuery
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_account_id, get_tenant_id
from app.api.schemas.documents import (
    DocumentChunkList,
    DocumentChunkListQuery,
    DocumentChunkMatch,
    DocumentChunkMatchList,
    DocumentChunkMatchQuery,
    DocumentChunkSchema,
)
from app.api.utils import DEFAULT_HTTP_EXCEPTION_RESPONSES
from app.core.database import get_db
from app.core.pipeline_versions import resolve_doc_pipeline_key
from app.models.document import Document, DocumentChunk
from app.services import dataset_service
from app.services.document_access_service import assert_document_readable_for_lifecycle

router = APIRouter(responses=DEFAULT_HTTP_EXCEPTION_RESPONSES)


@router.get("/{document_id}/chunks", response_model=DocumentChunkList)
def list_document_chunks(
    document_id: UUID,
    params: Annotated[DocumentChunkListQuery, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> DocumentChunkList:
    """
    List document chunks (paged).

    This is preferred over `include_chunks=true` for large documents to avoid huge payloads.
    """
    document = _get_readable_document(db, document_id=document_id, tenant_id=tenant_id, account_id=account_id)
    query = _document_chunks_query(
        db, document=document, pipeline_hash=params.pipeline_hash, all_versions=params.all_versions
    )
    if params.q is not None:
        term = params.q.strip()
        if term:
            query = query.filter(DocumentChunk.content.ilike(f"%{term}%"))

    total = query.count()
    items = query.order_by(DocumentChunk.chunk_index.asc()).offset(params.skip).limit(params.limit).all()
    return DocumentChunkList(total=total, items=items)


@router.get("/{document_id}/chunks/matches", response_model=DocumentChunkMatchList)
def list_document_chunk_matches(
    document_id: UUID,
    params: Annotated[DocumentChunkMatchQuery, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> DocumentChunkMatchList:
    """
    List chunk matches for a document (lightweight payload).

    This is optimized for "find in document" UX where the frontend only needs:
    - chunk id (for navigation / deep link)
    - chunk_index/page_number (for display)
    """
    document = _get_readable_document(db, document_id=document_id, tenant_id=tenant_id, account_id=account_id)
    term = params.q.strip()
    if not term:
        return DocumentChunkMatchList(total=0)

    query = (
        _document_chunks_query(
            db, document=document, pipeline_hash=params.pipeline_hash, all_versions=params.all_versions
        )
        .filter(DocumentChunk.content.ilike(f"%{term}%"))
        .order_by(DocumentChunk.chunk_index.asc())
    )
    total = query.count()
    rows = (
        query.with_entities(DocumentChunk.id, DocumentChunk.chunk_index, DocumentChunk.page_number)
        .limit(params.limit)
        .all()
    )
    items = [DocumentChunkMatch(id=row.id, chunk_index=row.chunk_index, page_number=row.page_number) for row in rows]

    return DocumentChunkMatchList(total=total, truncated=total > len(items), items=items)


@router.get("/{document_id}/chunks/{chunk_id}", response_model=DocumentChunkSchema)
def get_document_chunk(
    document_id: UUID,
    chunk_id: UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> DocumentChunk:
    """
    Get a single chunk for a document.
    """
    _get_readable_document(db, document_id=document_id, tenant_id=tenant_id, account_id=account_id)

    chunk = (
        db.query(DocumentChunk)
        .filter(
            DocumentChunk.tenant_id == tenant_id,
            DocumentChunk.document_id == document_id,
            DocumentChunk.id == chunk_id,
        )
        .first()
    )
    if chunk is None:
        raise HTTPException(status_code=404, detail="Chunk not found")

    return chunk


def _get_readable_document(db: Session, *, document_id: UUID, tenant_id: UUID, account_id: str) -> Document:
    dataset_service.ensure_member(db, tenant_id, account_id)
    document = db.query(Document).filter(Document.id == document_id, Document.tenant_id == tenant_id).first()
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    assert_document_readable_for_lifecycle(db, tenant_id=tenant_id, account_id=account_id, document=document)
    return document


def _document_chunks_query(
    db: Session, *, document: Document, pipeline_hash: str | None, all_versions: bool
) -> OrmQuery[DocumentChunk]:
    query = db.query(DocumentChunk).filter(
        DocumentChunk.tenant_id == document.tenant_id,
        DocumentChunk.document_id == document.id,
    )
    target_key = resolve_doc_pipeline_key(document.id, document.doc_metadata, pipeline_hash, all_versions=all_versions)
    if target_key is not None:
        query = query.filter(DocumentChunk.doc_metadata["doc_pipeline_key"].astext == target_key)
    return query
