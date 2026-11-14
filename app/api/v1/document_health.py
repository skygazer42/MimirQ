from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Query as ORMQuery
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_account_id, get_tenant_id
from app.api.schemas.documents import (
    DocumentHealthCard,
    DocumentHealthChunkCoverage,
    DocumentHealthChunking,
    DocumentHealthParsing,
    DocumentHealthQuery,
    DocumentHealthRetrievalHits,
    DocumentHealthSemanticQualitySummary,
)
from app.api.utils import DEFAULT_HTTP_EXCEPTION_RESPONSES
from app.core.database import get_db
from app.core.pipeline_versions import get_active_pipeline_hash, resolve_doc_pipeline_key
from app.models.document import Document, DocumentChunk
from app.rag.core.logging import get_logger
from app.services import dataset_service
from app.services.chunk_coverage_utils import compute_chunk_coverage_metrics_from_ranges
from app.services.document_access_service import assert_document_readable_for_lifecycle
from app.services.document_index_channel_service import summarize_document_index_channels

logger = get_logger(__name__)
router = APIRouter(responses=DEFAULT_HTTP_EXCEPTION_RESPONSES)


def _parsing_health(document: Document, meta: dict[str, Any]) -> DocumentHealthParsing:
    parsing = DocumentHealthParsing(
        parser_backend=meta.get("parser_backend"),
        parser_backend_requested=meta.get("parser_backend_requested"),
        parse_quality=meta.get("parse_quality"),
        pdf_quality=meta.get("pdf_quality"),
        seal_summary=meta.get("seal_summary"),
        processed_at=document.processed_at,
    )
    pdf_quality = parsing.pdf_quality
    if pdf_quality is None:
        return parsing

    is_scanned = pdf_quality.get("is_scanned")
    if isinstance(is_scanned, bool):
        parsing.is_scanned = is_scanned
    page_count = pdf_quality.get("page_count")
    if page_count is None:
        return parsing
    try:
        parsing.page_count = int(page_count)
    except (TypeError, ValueError, OverflowError):
        return parsing
    return parsing


def _semantic_quality_summary(
    chunk_query: ORMQuery[DocumentChunk], *, max_chunks_scored: int
) -> DocumentHealthSemanticQualitySummary | None:
    if max_chunks_scored == 0:
        return None
    from app.rag.chunking.quality_scorer import score_chunk_semantic_quality

    chunks = chunk_query.with_entities(DocumentChunk.content).limit(max_chunks_scored).all()
    if not chunks:
        return DocumentHealthSemanticQualitySummary(overall_histogram_10=[0] * 10)

    needs_review = 0
    information_density_sum = 0.0
    semantic_completeness_sum = 0.0
    self_containedness_sum = 0.0
    pronoun_ratio_sum = 0.0
    histogram = [0] * 10
    prev_token_set: set[str] | None = None
    for (content,) in chunks:
        scores, prev_token_set = score_chunk_semantic_quality(content, prev_token_set=prev_token_set)
        density = scores["information_density"]
        completeness = scores["semantic_completeness"]
        self_contained = scores["self_containedness"]
        pronoun_ratio = scores["pronoun_ratio"]
        information_density_sum += density
        semantic_completeness_sum += completeness
        self_containedness_sum += self_contained
        pronoun_ratio_sum += pronoun_ratio
        if scores["needs_review"]:
            needs_review += 1
        index = max(0, min(9, int(((density + completeness + self_contained) / 3.0) * 10.0)))
        histogram[index] += 1
    sampled = len(chunks)
    note = f"Scored first {sampled} chunks only (bounded)." if sampled >= max_chunks_scored else None
    return DocumentHealthSemanticQualitySummary(
        sampled_chunks=sampled,
        needs_review=needs_review,
        needs_review_ratio=needs_review / sampled,
        mean_information_density=round(information_density_sum / sampled, 4),
        mean_semantic_completeness=round(semantic_completeness_sum / sampled, 4),
        mean_self_containedness=round(self_containedness_sum / sampled, 4),
        mean_pronoun_ratio=round(pronoun_ratio_sum / sampled, 4),
        overall_histogram_10=histogram,
        note=note,
    )


def _best_effort_kg_report(
    *, db: Session, meta: dict[str, Any], tenant_id: UUID, document_id: UUID
) -> dict[str, Any] | None:
    try:
        from app.rag.kg.quality.kg_completeness_scorer import build_kg_quality_report

        return build_kg_quality_report(
            db,
            tenant_id=tenant_id,
            document_ids=[document_id],
            pipeline_hash=get_active_pipeline_hash(meta),
        )
    except Exception as exc:
        logger.warning(
            "Document health KG report unavailable document_id=%s error_type=%s", document_id, type(exc).__name__
        )
        return None


def _best_effort_retrieval_hits(
    *,
    tenant_id: UUID,
    document_id: UUID,
    window_minutes: int,
    max_bytes: int,
    generated_at: datetime,
) -> DocumentHealthRetrievalHits | None:
    try:
        from app.services.document_retrieval_hit_frequency import compute_document_retrieval_hit_frequency

        summary = compute_document_retrieval_hit_frequency(
            tenant_id=tenant_id,
            document_id=document_id,
            window_minutes=window_minutes,
            max_bytes=max_bytes,
            now=generated_at,
        )
        return DocumentHealthRetrievalHits.model_validate(summary)
    except Exception as exc:
        logger.warning(
            "Document health retrieval hits unavailable document_id=%s error_type=%s", document_id, type(exc).__name__
        )
        return None


def _best_effort_index_readiness(*, db: Session, document: Document) -> dict[str, Any] | None:
    try:
        return summarize_document_index_channels(db, document=document).to_dict()
    except Exception as exc:
        logger.warning(
            "Document health index readiness unavailable document_id=%s error_type=%s", document.id, type(exc).__name__
        )
        return None


@router.get("/{document_id}/health", response_model=DocumentHealthCard)
def get_document_health_card(
    document_id: UUID,
    params: Annotated[DocumentHealthQuery, Query()],
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> DocumentHealthCard:
    """
    Consolidated document health card (Gap10).

    PII-safe: returns aggregate signals only (no raw chunk text).
    """
    dataset_service.ensure_member(db, tenant_id, account_id)
    document = db.query(Document).filter(Document.id == document_id, Document.tenant_id == tenant_id).first()
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    assert_document_readable_for_lifecycle(db, tenant_id=tenant_id, account_id=account_id, document=document)
    generated_at = datetime.now(UTC)
    meta = document.doc_metadata
    if meta is None:
        meta = {}
    target_key = resolve_doc_pipeline_key(document_id, document.doc_metadata, None, all_versions=False)
    chunk_query = db.query(DocumentChunk).filter(
        DocumentChunk.tenant_id == tenant_id,
        DocumentChunk.document_id == document_id,
        DocumentChunk.disabled_at.is_(None),
    )
    if target_key is not None:
        chunk_query = chunk_query.filter(DocumentChunk.doc_metadata["doc_pipeline_key"].astext == target_key)
    chunk_query = chunk_query.order_by(DocumentChunk.chunk_index.asc())

    chunking = DocumentHealthChunking(
        chunk_strategy=meta.get("chunk_strategy"),
        chunk_strategy_requested=meta.get("chunk_strategy_requested"),
        chunk_count=document.chunk_count,
        total_characters=document.total_characters,
    )
    ranges = [
        (start, end)
        for start, end in chunk_query.with_entities(DocumentChunk.start_char, DocumentChunk.end_char).all()
        if start is not None and end is not None
    ]
    chunking.coverage = DocumentHealthChunkCoverage(
        **compute_chunk_coverage_metrics_from_ranges(ranges, total_characters=chunking.total_characters)
    )
    chunking.semantic_quality = _semantic_quality_summary(chunk_query, max_chunks_scored=params.max_chunks_scored)
    return DocumentHealthCard(
        document_id=document.id,
        dataset_id=document.dataset_id,
        filename=document.filename,
        file_type=document.file_type,
        file_size=document.file_size,
        created_at=document.created_at,
        updated_at=document.updated_at,
        generated_at=generated_at,
        status=document.status,
        parsing=_parsing_health(document, meta),
        chunking=chunking,
        kg=_best_effort_kg_report(db=db, meta=meta, tenant_id=tenant_id, document_id=document_id),
        retrieval_hits=_best_effort_retrieval_hits(
            tenant_id=tenant_id,
            document_id=document_id,
            window_minutes=params.window_minutes,
            max_bytes=params.max_bytes,
            generated_at=generated_at,
        ),
        index_readiness=_best_effort_index_readiness(db=db, document=document),
    )
