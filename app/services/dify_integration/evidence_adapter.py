"""Dify evidence adapter operations."""

import time
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.api.schemas.chat import ChatRAGConfig
from app.core.config import settings
from app.rag.core.logging import get_logger
from app.services.dify_integration import anchor_strength, common, scoring

logger = get_logger(__name__)


async def retrieve_dataset_citations(
    *,
    db: Session,
    tenant_id: UUID,
    account_id: str,
    dataset_ids: list[UUID],
    query: str,
    top_k: int,
    score_threshold: float,
    metadata_filter: dict[str, Any] | None = None,
    requested_top_k: int,
    enable_kg_query_expansion: bool,
    enable_kg_chunk_injection: bool,
    kg_chunk_injection_max_chunks: int | None = None,
    enable_kg_chunk_boost: bool,
    kg_chunk_boost_weight: float | None = None,
    kg_chunk_boost_max_promoted: int | None = None,
    enable_reranker: bool,
    retrieval_mode: str = "hybrid",
) -> list[dict[str, Any]]:
    from app.api.v1.rag import EvidenceRetrieveRequest, retrieve_evidence

    started = time.perf_counter()
    evidence_top_k = max(1, int(top_k or 1))
    overfetch_multiplier = max(1, settings.DIFY_EXTERNAL_KNOWLEDGE_RETRIEVAL_OVERFETCH_MULTIPLIER)
    overfetch_max_k = max(
        0,
        settings.DIFY_EXTERNAL_KNOWLEDGE_RETRIEVAL_OVERFETCH_MAX_K,
    )
    if overfetch_max_k <= 0:
        overfetch_max_k = evidence_top_k

    reranker_top_n = max(evidence_top_k, settings.RERANKER_TOP_N)
    rag_config = ChatRAGConfig(
        top_k=evidence_top_k,
        score_threshold=score_threshold,
        retrieval_mode=str(retrieval_mode or "hybrid"),
        visible_evidence_only=True,
        metadata_filter=metadata_filter,
        enable_reranker=enable_reranker,
        reranker_provider=(settings.RERANKER_PROVIDER or "llm") if enable_reranker else "none",
        reranker_top_n=reranker_top_n,
        lexical_db_hybrid_fallback_only=settings.DIFY_EXTERNAL_KNOWLEDGE_LEXICAL_DB_HYBRID_FALLBACK_ONLY,
        lexical_db_hybrid_metadata_exact_fallback_enabled=settings.DIFY_EXTERNAL_KNOWLEDGE_LEXICAL_METADATA_EXACT_FALLBACK_ENABLED,
        metadata_exact_db_fallback_enabled=settings.DIFY_EXTERNAL_KNOWLEDGE_METADATA_EXACT_DB_FALLBACK_ENABLED,
        retrieval_overfetch_multiplier=overfetch_multiplier,
        retrieval_overfetch_max_k=overfetch_max_k,
        enable_kg_query_expansion=enable_kg_query_expansion,
        enable_kg_chunk_injection=enable_kg_chunk_injection,
        kg_chunk_injection_max_chunks=(
            anchor_strength._dify_kg_int("DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_INJECTION_MAX_CHUNKS", 3)
            if kg_chunk_injection_max_chunks is None
            else int(kg_chunk_injection_max_chunks)
        ),
        enable_kg_chunk_boost=enable_kg_chunk_boost,
        kg_chunk_boost_weight=(
            anchor_strength._dify_kg_float("DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_BOOST_WEIGHT", 0.25)
            if kg_chunk_boost_weight is None
            else float(kg_chunk_boost_weight)
        ),
        kg_chunk_boost_max_promoted=(
            anchor_strength._dify_kg_int("DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_BOOST_MAX_PROMOTED", 2)
            if kg_chunk_boost_max_promoted is None
            else int(kg_chunk_boost_max_promoted)
        ),
    )

    scoped_dataset_ids = common._dedupe_dataset_ids(dataset_ids)
    response = await retrieve_evidence(
        body=EvidenceRetrieveRequest(query=query, rag_config=rag_config, dataset_ids=scoped_dataset_ids),
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    metrics = response.metrics
    trace = response.retrieval_trace or {}
    logger.info(
        "Dify evidence retrieve completed query_hash=%s dataset_count=%s top_k=%s requested_top_k=%s "
        "citations=%s elapsed_ms=%s retrieval_elapsed_sec=%s vector_backend=%s retrieval_mode=%s "
        "post_rerank_elapsed_sec=%s hard_fallback_elapsed_sec=%s trace_passes=%s",
        scoring._diagnostic_query_hash(query),
        len(scoped_dataset_ids),
        evidence_top_k,
        requested_top_k,
        len(response.citations),
        elapsed_ms,
        metrics.get("retrieval_elapsed_sec"),
        metrics.get("vector_backend"),
        metrics.get("retrieval_mode") or metrics.get("requested_retrieval_mode"),
        metrics.get("evidence_post_rerank_elapsed_sec"),
        metrics.get("hard_fallback_elapsed_sec"),
        len(trace.get("passes") or []) if isinstance(trace, dict) else 0,
    )
    return list(response.citations)
