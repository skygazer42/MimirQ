from __future__ import annotations

import uuid
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.document import DocumentChunkList, DocumentChunkMatchList, DocumentChunkSchema
from app.core.database import get_db
from app.models.dataset import Dataset
from app.models.document import Document as DBDocument
from app.models.document import DocumentChunk
from app.services.dataset_service import DatasetService
from app.services.document_access_service import assert_document_acl_readable

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

DOC_NOT_FOUND_DETAIL = "Document not found"
CHUNK_NOT_FOUND_DETAIL = "Chunk not found"

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)


@router.get("/{document_id}/chunks", response_model=DocumentChunkList, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def list_document_chunks(
    document_id: uuid.UUID,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=2000)] = 500,
    q: Annotated[str | None, Query(max_length=200)] = None,
    pipeline_hash: Annotated[str | None, Query(max_length=64, description="Optional: filter by a specific pipeline_hash version")] = None,
    all_versions: Annotated[bool, Query(description="If true, return chunks across all pipeline versions (debug)")] = False,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    List document chunks (paged).

    This is preferred over `include_chunks=true` for large documents to avoid huge payloads.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)

    document = (
        db.query(DBDocument)
        .filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id)
        .first()
    )
    if not document:
        raise HTTPException(status_code=404, detail=DOC_NOT_FOUND_DETAIL)

    dataset: Dataset | None = None
    if document.dataset_id:
        dataset = DatasetService.get_dataset(db, tenant_id, document.dataset_id)
        DatasetService.assert_dataset_readable(db, dataset, account_id)
    assert_document_acl_readable(db, tenant_id=tenant_id, account_id=account_id, document=document, dataset=dataset)

    query = db.query(DocumentChunk).filter(
        DocumentChunk.tenant_id == tenant_id,
        DocumentChunk.document_id == document_id,
    )

    if not all_versions:
        from app.core.pipeline_versions import resolve_doc_pipeline_key

        target_key = resolve_doc_pipeline_key(
            document_id,
            getattr(document, "doc_metadata", None),
            pipeline_hash,
            all_versions=all_versions,
        )
        if target_key:
            query = query.filter(
                DocumentChunk.doc_metadata["doc_pipeline_key"].astext == target_key  # type: ignore[attr-defined]
            )

    if q:
        term = q.strip()
        if term:
            query = query.filter(DocumentChunk.content.ilike(f"%{term}%"))

    total = query.count()
    items = query.order_by(DocumentChunk.chunk_index.asc()).offset(skip).limit(limit).all()
    return {"total": total, "items": items}


@router.get("/{document_id}/chunks/matches", response_model=DocumentChunkMatchList, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def list_document_chunk_matches(
    document_id: uuid.UUID,
    q: Annotated[str, Query(..., max_length=200, description="Case-insensitive substring match against chunk content")],
    limit: Annotated[int, Query(ge=1, le=5000, description="Max returned matches (may be truncated)")] = 2000,
    pipeline_hash: Annotated[str | None, Query(max_length=64, description="Optional: filter by a specific pipeline_hash version")] = None,
    all_versions: Annotated[bool, Query(description="If true, return matches across all pipeline versions (debug)")] = False,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    List chunk matches for a document (lightweight payload).

    This is optimized for "find in document" UX where the frontend only needs:
    - chunk id (for navigation / deep link)
    - chunk_index/page_number (for display)
    """
    DatasetService.ensure_member(db, tenant_id, account_id)

    document = (
        db.query(DBDocument)
        .filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id)
        .first()
    )
    if not document:
        raise HTTPException(status_code=404, detail=DOC_NOT_FOUND_DETAIL)

    dataset: Dataset | None = None
    if document.dataset_id:
        dataset = DatasetService.get_dataset(db, tenant_id, document.dataset_id)
        DatasetService.assert_dataset_readable(db, dataset, account_id)
    assert_document_acl_readable(db, tenant_id=tenant_id, account_id=account_id, document=document, dataset=dataset)

    term = (q or "").strip()
    if not term:
        return {"total": 0, "truncated": False, "items": []}

    query = (
        db.query(DocumentChunk)
        .filter(
            DocumentChunk.tenant_id == tenant_id,
            DocumentChunk.document_id == document_id,
            DocumentChunk.content.ilike(f"%{term}%"),
        )
        .order_by(DocumentChunk.chunk_index.asc())
    )
    if not all_versions:
        from app.core.pipeline_versions import resolve_doc_pipeline_key

        target_key = resolve_doc_pipeline_key(
            document_id,
            getattr(document, "doc_metadata", None),
            pipeline_hash,
            all_versions=all_versions,
        )
        if target_key:
            query = query.filter(
                DocumentChunk.doc_metadata["doc_pipeline_key"].astext == target_key  # type: ignore[attr-defined]
            )

    total = int(query.count())
    rows = (
        query.with_entities(DocumentChunk.id, DocumentChunk.chunk_index, DocumentChunk.page_number)
        .limit(limit)
        .all()
    )
    items = [
        {
            "id": str(row[0]),
            "chunk_index": int(row[1]),
            "page_number": row[2] if row[2] is None else int(row[2]),
        }
        for row in rows
    ]

    return {
        "total": total,
        "truncated": total > len(items),
        "items": items,
    }


@router.get("/{document_id}/chunks/{chunk_id}", response_model=DocumentChunkSchema, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def get_document_chunk(
    document_id: uuid.UUID,
    chunk_id: uuid.UUID,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Get a single chunk for a document.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)

    document = (
        db.query(DBDocument)
        .filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id)
        .first()
    )
    if not document:
        raise HTTPException(status_code=404, detail=DOC_NOT_FOUND_DETAIL)

    dataset: Dataset | None = None
    if document.dataset_id:
        dataset = DatasetService.get_dataset(db, tenant_id, document.dataset_id)
        DatasetService.assert_dataset_readable(db, dataset, account_id)
    assert_document_acl_readable(db, tenant_id=tenant_id, account_id=account_id, document=document, dataset=dataset)

    chunk = (
        db.query(DocumentChunk)
        .filter(
            DocumentChunk.tenant_id == tenant_id,
            DocumentChunk.document_id == document_id,
            DocumentChunk.id == chunk_id,
        )
        .first()
    )
    if not chunk:
        raise HTTPException(status_code=404, detail=CHUNK_NOT_FOUND_DETAIL)

    return chunk
