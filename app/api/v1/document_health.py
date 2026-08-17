import uuid
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.document_health import (
    DocumentHealthCard,
    DocumentHealthChunkCoverage,
    DocumentHealthChunking,
    DocumentHealthParsing,
    DocumentHealthRetrievalHits,
    DocumentHealthSemanticQualitySummary,
)
from app.core.database import get_db
from app.models.dataset import Dataset
from app.models.document import Document as DBDocument
from app.models.document import DocumentChunk
from app.rag.core.logging import get_logger
from app.services.chunk_coverage_utils import compute_chunk_coverage_metrics_from_ranges
from app.services.dataset_service import DatasetService
from app.services.document_access_service import assert_document_acl_readable
from app.services.document_index_channel_service import summarize_document_index_channels

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

DOC_NOT_FOUND_DETAIL = "Document not found"

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)


def _get_health_document_or_404(*, db: Session, tenant_id: UUID, document_id: UUID):
    document = (
        db.query(DBDocument)
        .filter(
            DBDocument.id == document_id,
            DBDocument.tenant_id == tenant_id,
        )
        .first()
    )
    if not document:
        raise HTTPException(status_code=404, detail=DOC_NOT_FOUND_DETAIL)
    return document


def _authorize_health_document(*, db: Session, tenant_id: UUID, account_id: str, document) -> None:
    dataset: Dataset | None = None
    if document.dataset_id:
        dataset = DatasetService.get_dataset(db, tenant_id, document.dataset_id)
        DatasetService.assert_dataset_readable(db, dataset, account_id)
    assert_document_acl_readable(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        document=document,
        dataset=dataset,
    )


def _parsing_health(document, meta: dict[str, Any]) -> DocumentHealthParsing:
    pdf_quality = meta.get("pdf_quality") if isinstance(meta.get("pdf_quality"), dict) else None
    is_scanned = (
        bool(pdf_quality.get("is_scanned"))
        if isinstance(pdf_quality, dict) and isinstance(pdf_quality.get("is_scanned"), bool)
        else None
    )
    try:
        page_count = (
            int(pdf_quality.get("page_count"))
            if isinstance(pdf_quality, dict) and pdf_quality.get("page_count") is not None
            else None
        )
    except Exception:
        page_count = None
    return DocumentHealthParsing(
        parser_backend=(str(meta.get("parser_backend") or "").strip() or None),
        parser_backend_requested=(str(meta.get("parser_backend_requested") or "").strip() or None),
        parse_quality=meta.get("parse_quality") if isinstance(meta.get("parse_quality"), dict) else None,
        pdf_quality=pdf_quality,
        seal_summary=meta.get("seal_summary") if isinstance(meta.get("seal_summary"), dict) else None,
        is_scanned=is_scanned,
        page_count=page_count,
        processed_at=getattr(document, "processed_at", None),
    )


def _document_target_pipeline_key(document_id: UUID, document) -> str | None:
    from app.core.pipeline_versions import resolve_doc_pipeline_key

    return resolve_doc_pipeline_key(
        document_id,
        getattr(document, "doc_metadata", None),
        pipeline_hash=None,
        all_versions=False,
    )


def _load_health_chunk_ranges(
    *, db: Session, tenant_id: UUID, document_id: UUID, target_key: str | None
) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    chunk_query = db.query(DocumentChunk.start_char, DocumentChunk.end_char).filter(
        DocumentChunk.tenant_id == tenant_id,
        DocumentChunk.document_id == document_id,
        DocumentChunk.disabled_at.is_(None),
    )
    if target_key:
        chunk_query = chunk_query.filter(
            DocumentChunk.doc_metadata["doc_pipeline_key"].astext == target_key  # type: ignore[attr-defined]
        )
    for start, end in chunk_query.order_by(DocumentChunk.chunk_index.asc()).all():
        if start is None or end is None:
            continue
        try:
            ranges.append((int(start), int(end)))
        except Exception:
            get_logger(__name__).debug("Skipping item after non-critical exception", exc_info=True)
    return ranges


def _semantic_quality_summary(
    *,
    db: Session,
    tenant_id: UUID,
    document_id: UUID,
    document,
    target_key: str | None,
    max_chunks_scored: int,
) -> DocumentHealthSemanticQualitySummary | None:
    max_chunks_scored_i = max(0, int(max_chunks_scored or 0))
    if not max_chunks_scored_i:
        return None
    from app.rag.chunking.quality_scorer import score_chunk_semantic_quality

    chunks_q = db.query(DocumentChunk.content).filter(
        DocumentChunk.tenant_id == tenant_id,
        DocumentChunk.document_id == document_id,
        DocumentChunk.disabled_at.is_(None),
    )
    if target_key:
        chunks_q = chunks_q.filter(
            DocumentChunk.doc_metadata["doc_pipeline_key"].astext == target_key  # type: ignore[attr-defined]
        )
    chunks = chunks_q.order_by(DocumentChunk.chunk_index.asc()).limit(max_chunks_scored_i).all()
    sampled = 0
    needs_review = 0
    sum_density = 0.0
    sum_complete = 0.0
    sum_self = 0.0
    sum_pronoun = 0.0
    hist = [0 for _ in range(10)]
    prev_token_set: set[str] | None = None
    for (content,) in chunks:
        sampled += 1
        scores, prev_token_set = score_chunk_semantic_quality(str(content or ""), prev_token_set=prev_token_set)
        density = float(scores.get("information_density") or 0.0)
        completeness = float(scores.get("semantic_completeness") or 0.0)
        self_contained = float(scores.get("self_containedness") or 0.0)
        pronoun_ratio = float(scores.get("pronoun_ratio") or 0.0)
        sum_density += density
        sum_complete += completeness
        sum_self += self_contained
        sum_pronoun += pronoun_ratio
        if bool(scores.get("needs_review")):
            needs_review += 1
        idx = max(0, min(9, int(((density + completeness + self_contained) / 3.0) * 10.0)))
        hist[idx] += 1
    note = f"Scored first {sampled} chunks only (bounded)." if sampled >= max_chunks_scored_i else None
    return DocumentHealthSemanticQualitySummary(
        sampled_chunks=int(sampled),
        needs_review=int(needs_review),
        needs_review_ratio=float(needs_review / max(1, sampled)),
        mean_information_density=float(round(sum_density / max(1, sampled), 4)) if sampled else None,
        mean_semantic_completeness=float(round(sum_complete / max(1, sampled), 4)) if sampled else None,
        mean_self_containedness=float(round(sum_self / max(1, sampled), 4)) if sampled else None,
        mean_pronoun_ratio=float(round(sum_pronoun / max(1, sampled), 4)) if sampled else None,
        overall_histogram_10=[int(x) for x in hist],
        note=note,
    )


def _best_effort_kg_report(
    *, db: Session, meta: dict[str, Any], tenant_id: UUID, document_id: UUID
) -> dict[str, Any] | None:
    try:
        from app.core.pipeline_versions import get_active_pipeline_hash
        from app.rag.kg.quality.kg_completeness_scorer import build_kg_quality_report

        return build_kg_quality_report(
            db,
            tenant_id=tenant_id,
            document_ids=[document_id],
            pipeline_hash=get_active_pipeline_hash(meta),
        )
    except Exception:
        return None


def _best_effort_retrieval_hits(
    *,
    tenant_id: UUID,
    document_id: UUID,
    window_minutes: int,
    max_bytes: int,
    now0: datetime,
) -> DocumentHealthRetrievalHits | None:
    try:
        from app.services.document_retrieval_hit_frequency import compute_document_retrieval_hit_frequency

        return DocumentHealthRetrievalHits(
            **compute_document_retrieval_hit_frequency(
                tenant_id=tenant_id,
                document_id=document_id,
                window_minutes=int(window_minutes or 0),
                max_bytes=int(max_bytes or 0),
                now=now0,
            )
        )
    except Exception:
        return None


def _best_effort_index_readiness(*, db: Session, document):
    try:
        return summarize_document_index_channels(db, document=document).to_dict()
    except Exception:
        return None


@router.get("/{document_id}/health", response_model=DocumentHealthCard, responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
def get_document_health_card(
    document_id: uuid.UUID,
    window_minutes: Annotated[int, Query(ge=1, le=60 * 24 * 30, description="Metrics lookback window (minutes)")] = 60,
    max_bytes: Annotated[
        int, Query(ge=1, le=50_000_000, description="Max bytes to read from metrics JSONL tail")
    ] = 5_000_000,
    max_chunks_scored: Annotated[
        int, Query(ge=0, le=2048, description="Max chunks to score for semantic quality")
    ] = 256,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
):
    """
    Consolidated document health card (Gap10).

    PII-safe: returns aggregate signals only (no raw chunk text).
    """
    DatasetService.ensure_member(db, tenant_id, account_id)
    document = _get_health_document_or_404(db=db, tenant_id=tenant_id, document_id=document_id)
    _authorize_health_document(db=db, tenant_id=tenant_id, account_id=account_id, document=document)
    now0 = datetime.now(UTC)
    meta = dict(getattr(document, "doc_metadata", None) or {})
    target_key = _document_target_pipeline_key(document_id, document)
    coverage_out = DocumentHealthChunkCoverage(
        **compute_chunk_coverage_metrics_from_ranges(
            _load_health_chunk_ranges(
                db=db,
                tenant_id=tenant_id,
                document_id=document_id,
                target_key=target_key,
            ),
            total_characters=int(getattr(document, "total_characters", 0) or 0),
        )
    )
    chunking = DocumentHealthChunking(
        chunk_strategy=(str(meta.get("chunk_strategy") or "").strip() or None),
        chunk_strategy_requested=(str(meta.get("chunk_strategy_requested") or "").strip() or None),
        chunk_count=int(getattr(document, "chunk_count", 0) or 0),
        total_characters=int(getattr(document, "total_characters", 0) or 0),
        coverage=coverage_out,
        semantic_quality=_semantic_quality_summary(
            db=db,
            tenant_id=tenant_id,
            document_id=document_id,
            document=document,
            target_key=target_key,
            max_chunks_scored=max_chunks_scored,
        ),
    )

    return DocumentHealthCard(
        document_id=document.id,
        dataset_id=document.dataset_id,
        filename=getattr(document, "filename", None),
        file_type=getattr(document, "file_type", None),
        file_size=(
            int(getattr(document, "file_size", 0) or 0) if getattr(document, "file_size", None) is not None else None
        ),
        created_at=getattr(document, "created_at", None),
        updated_at=getattr(document, "updated_at", None),
        generated_at=now0,
        status=str(getattr(document, "status", None) or "") or None,
        parsing=_parsing_health(document, meta),
        chunking=chunking,
        kg=_best_effort_kg_report(db=db, meta=meta, tenant_id=tenant_id, document_id=document_id),
        retrieval_hits=_best_effort_retrieval_hits(
            tenant_id=tenant_id,
            document_id=document_id,
            window_minutes=int(window_minutes or 0),
            max_bytes=int(max_bytes or 0),
            now0=now0,
        ),
        index_readiness=_best_effort_index_readiness(db=db, document=document),
    )
