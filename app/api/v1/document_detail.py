from __future__ import annotations

import uuid
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.document import DocumentDetail
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

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)


@router.get("/{document_id}", response_model=DocumentDetail, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def get_document(
    document_id: uuid.UUID,
    include_chunks: bool = False,
    pipeline_hash: Annotated[
        str | None,
        Query(max_length=64, description="Optional: filter chunks by a specific pipeline_hash version (when include_chunks=true)"),
    ] = None,
    all_versions: Annotated[
        bool,
        Query(description="If true, include chunks across all pipeline versions (debug; when include_chunks=true)"),
    ] = False,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Get document detail.
    """
    DatasetService.ensure_member(db, tenant_id, account_id)
    query = db.query(DBDocument).filter(
        DBDocument.id == document_id,
        DBDocument.tenant_id == tenant_id,
    )
    document = query.first()

    if not document:
        raise HTTPException(status_code=404, detail=DOC_NOT_FOUND_DETAIL)

    dataset: Dataset | None = None
    if document.dataset_id:
        dataset = DatasetService.get_dataset(db, tenant_id, document.dataset_id)
        DatasetService.assert_dataset_readable(db, dataset, account_id)
    assert_document_acl_readable(db, tenant_id=tenant_id, account_id=account_id, document=document, dataset=dataset)

    if include_chunks:
        chunk_query = db.query(DocumentChunk).filter(
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
                chunk_query = chunk_query.filter(
                    DocumentChunk.doc_metadata["doc_pipeline_key"].astext == target_key  # type: ignore[attr-defined]
                )

        chunks = chunk_query.order_by(DocumentChunk.chunk_index.asc()).all()
        document.chunks_loaded = chunks

    return document
