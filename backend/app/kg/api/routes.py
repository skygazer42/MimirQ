from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.dependencies.auth import get_current_account_id
from app.dependencies.tenant import get_tenant_id
from app.models.document import Document as DBDocument, DocumentChunk
from app.kg.schemas import SAGExtractResponse, SAGSearchRequest, SAGSearchResponse
from app.services.document_access import filter_allowed_document_ids
from app.services.dataset_service import DatasetService
from app.kg.pipeline import extract_events, sag_search

router = APIRouter()


def _ensure_enabled():
    if not settings.SAG_ENABLED:
        raise HTTPException(
            status_code=503,
            detail="SAG is disabled. Set SAG_ENABLED=true in your environment to enable it.",
        )


@router.post("/documents/{document_id}/extract", response_model=SAGExtractResponse)
async def run_sag_extraction_for_document(
    document_id: UUID,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """
    Trigger SAG extraction for a processed document (rebuilds events/entities from chunks).
    """
    _ensure_enabled()

    document = (
        db.query(DBDocument)
        .filter(DBDocument.id == document_id, DBDocument.tenant_id == tenant_id)
        .first()
    )
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    if document.dataset_id:
        dataset = DatasetService.get_dataset(db, tenant_id, document.dataset_id)
        DatasetService.assert_dataset_readable(db, dataset, account_id)

    chunks = (
        db.query(DocumentChunk)
        .filter(
            DocumentChunk.document_id == document_id,
            DocumentChunk.tenant_id == tenant_id,
        )
        .order_by(DocumentChunk.chunk_index)
        .all()
    )
    if not chunks:
        raise HTTPException(
            status_code=400,
            detail="Document has no chunks yet. Process the document first.",
        )

    events = await extract_events([c.id for c in chunks], tenant_id=tenant_id)

    return SAGExtractResponse(
        document_id=document_id,
        chunk_count=len(chunks),
        event_count=len(events),
    )


@router.post("/search", response_model=SAGSearchResponse)
async def run_sag_search(
    payload: SAGSearchRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """
    Run SAG search (query -> recall/expand/rerank) for the current tenant.
    """
    _ensure_enabled()
    DatasetService.ensure_member(db, tenant_id, account_id)

    if not payload.document_ids:
        raise HTTPException(status_code=400, detail="document_ids are required for SAG search")

    allowed_doc_ids = filter_allowed_document_ids(db, tenant_id, account_id, payload.document_ids)

    try:
        result = await sag_search(
            query=payload.query,
            tenant_id=tenant_id,
            document_ids=allowed_doc_ids,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"SAG search failed: {exc}") from exc

    return SAGSearchResponse(result=result, query=payload.query)
