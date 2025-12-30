from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.models.document import Document as DBDocument, DocumentChunk
from app.rag.kg.schemas import KGExtractResponse, KGSearchRequest, KGSearchResponse
from app.services.document_access import filter_allowed_document_ids
from app.services.dataset_service import DatasetService
from app.rag.kg.pipeline import extract_events, kg_search

router = APIRouter()


def _ensure_enabled():
    if not settings.KG_ENABLED:
        raise HTTPException(
            status_code=503,
            detail="KG is disabled. Set KG_ENABLED=true in your environment to enable it.",
        )


@router.post("/documents/{document_id}/extract", response_model=KGExtractResponse)
async def run_kg_extraction_for_document(
    document_id: UUID,
    prompt_template_id: UUID | None = Query(default=None),
    prompt_template_key: str | None = Query(default=None),
    prompt_ab_experiment_key: str | None = Query(default=None),
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """
    Trigger KG extraction for a processed document (rebuilds events/entities from chunks).
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

    eff_prompt_template_id = prompt_template_id
    if eff_prompt_template_id is None:
        raw_tid = (getattr(settings, "KG_EXTRACT_PROMPT_TEMPLATE_ID", "") or "").strip()
        if raw_tid:
            try:
                eff_prompt_template_id = UUID(raw_tid)
            except Exception:
                eff_prompt_template_id = None

    eff_prompt_template_key = (prompt_template_key or "").strip() or (getattr(settings, "KG_EXTRACT_PROMPT_TEMPLATE_KEY", "") or "").strip() or None
    eff_prompt_ab_experiment_key = (prompt_ab_experiment_key or "").strip() or (getattr(settings, "KG_EXTRACT_PROMPT_AB_EXPERIMENT_KEY", "") or "").strip() or None

    events = await extract_events(
        [c.id for c in chunks],
        tenant_id=tenant_id,
        chunks=chunks,
        prompt_template_id=eff_prompt_template_id,
        prompt_template_key=eff_prompt_template_key,
        prompt_ab_experiment_key=eff_prompt_ab_experiment_key,
        ab_user_key=account_id,
    )

    return KGExtractResponse(
        document_id=document_id,
        chunk_count=len(chunks),
        event_count=len(events),
    )


@router.post("/search", response_model=KGSearchResponse)
async def run_kg_search(
    payload: KGSearchRequest,
    tenant_id: UUID = Depends(get_tenant_id),
    account_id: str = Depends(get_current_account_id),
    db: Session = Depends(get_db),
):
    """
    Run KG search (query -> recall/expand/rerank) for the current tenant.
    """
    _ensure_enabled()
    DatasetService.ensure_member(db, tenant_id, account_id)

    if not payload.document_ids:
        raise HTTPException(status_code=400, detail="document_ids are required for KG search")

    allowed_doc_ids = filter_allowed_document_ids(db, tenant_id, account_id, payload.document_ids)

    try:
        result = await kg_search(
            query=payload.query,
            tenant_id=tenant_id,
            document_ids=allowed_doc_ids,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"KG search failed: {exc}") from exc

    return KGSearchResponse(result=result, query=payload.query)
