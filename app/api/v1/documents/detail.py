from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

import app.services.datasets.management as dataset_service
from app.api.dependencies import get_current_account_id, get_tenant_id
from app.api.schemas.documents import DocumentDetail, DocumentDetailQuery
from app.api.utils import DEFAULT_HTTP_EXCEPTION_RESPONSES
from app.infrastructure.database.connection import get_db
from app.models.documents.records import Document, DocumentChunk
from app.services.documents.access import assert_document_readable_for_lifecycle, get_document_for_lifecycle
from app.services.documents.pipeline_versions import resolve_doc_pipeline_key
from app.services.documents.runtime_metadata import attach_runtime_document_metadata

router = APIRouter(responses=DEFAULT_HTTP_EXCEPTION_RESPONSES)


@router.get("/{document_id}", response_model=DocumentDetail)
def get_document(
    document_id: UUID,
    params: Annotated[DocumentDetailQuery, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> Document:
    """
    Get document detail.
    """
    dataset_service.ensure_member(db, tenant_id, account_id)
    document = get_document_for_lifecycle(db, tenant_id, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    assert_document_readable_for_lifecycle(db, tenant_id=tenant_id, account_id=account_id, document=document)

    if params.include_chunks:
        chunk_query = db.query(DocumentChunk).filter(
            DocumentChunk.tenant_id == tenant_id,
            DocumentChunk.document_id == document_id,
        )

        target_key = resolve_doc_pipeline_key(
            document_id, document.doc_metadata, params.pipeline_hash, all_versions=params.all_versions
        )
        if target_key is not None:
            chunk_query = chunk_query.filter(DocumentChunk.doc_metadata["doc_pipeline_key"].astext == target_key)
        document.chunks_loaded = chunk_query.order_by(DocumentChunk.chunk_index.asc()).all()
    attach_runtime_document_metadata(document)

    return document
