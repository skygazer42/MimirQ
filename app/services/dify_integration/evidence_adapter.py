"""Dify evidence adapter operations."""

import time
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.core.config import settings
from app.rag.core.logging import get_logger
from app.services.dify_integration import anchor_strength, common, request_preferences, scoring
from app.types.rag_config import ChatRAGConfig

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
    requested_top_k: int | None = None,
    enable_kg_query_expansion: bool | None = None,
    enable_kg_chunk_injection: bool | None = None,
    kg_chunk_injection_max_chunks: int | None = None,
    enable_kg_chunk_boost: bool | None = None,
    kg_chunk_boost_weight: float | None = None,
    kg_chunk_boost_max_promoted: int | None = None,
    enable_reranker: bool | None = None,
    retrieval_mode: str = "hybrid",
) -> list[dict[str, Any]]:
    from app.services import evidence_retrieval
    from app.types.evidence_retrieval import EvidenceRetrieveRequest

    started = time.perf_counter()
    evidence_top_k = max(1, int(top_k or 1))
    if requested_top_k is None:
        evidence_top_k = request_preferences._resolve_internal_candidate_top_k(evidence_top_k)

    kg_query_expansion_enabled = (
        anchor_strength._dify_kg_bool("DIFY_EXTERNAL_KNOWLEDGE_KG_QUERY_EXPANSION_ENABLED", False)
        if enable_kg_query_expansion is None
        else bool(enable_kg_query_expansion)
    )
    kg_chunk_injection_enabled = (
        anchor_strength._dify_kg_bool("DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_INJECTION_ENABLED", False)
        if enable_kg_chunk_injection is None
        else bool(enable_kg_chunk_injection)
    )
    kg_chunk_boost_enabled = (
        anchor_strength._dify_kg_bool("DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_BOOST_ENABLED", False)
        if enable_kg_chunk_boost is None
        else bool(enable_kg_chunk_boost)
    )
    overfetch_multiplier = max(
        1,
        (settings.DIFY_EXTERNAL_KNOWLEDGE_RETRIEVAL_OVERFETCH_MULTIPLIER or 1),
    )
    overfetch_max_k = max(
        0,
        settings.DIFY_EXTERNAL_KNOWLEDGE_RETRIEVAL_OVERFETCH_MAX_K,
    )
    if overfetch_max_k <= 0:
        overfetch_max_k = evidence_top_k

    reranker_enabled = scoring._dify_external_reranker_enabled() if enable_reranker is None else bool(enable_reranker)
    reranker_top_n = max(
        1,
        int(getattr(settings, "RERANKER_TOP_N", evidence_top_k) or evidence_top_k),
        int(evidence_top_k or 1),
    )
    rag_config = ChatRAGConfig(
        top_k=evidence_top_k,
        score_threshold=score_threshold,
        retrieval_mode=str(retrieval_mode or "hybrid"),
        visible_evidence_only=True,
        metadata_filter=metadata_filter,
        enable_reranker=reranker_enabled,
        reranker_provider=(settings.RERANKER_PROVIDER or "llm") if reranker_enabled else "none",
        reranker_top_n=reranker_top_n,
        lexical_db_hybrid_fallback_only=settings.DIFY_EXTERNAL_KNOWLEDGE_LEXICAL_DB_HYBRID_FALLBACK_ONLY,
        lexical_db_hybrid_metadata_exact_fallback_enabled=settings.DIFY_EXTERNAL_KNOWLEDGE_LEXICAL_METADATA_EXACT_FALLBACK_ENABLED,
        metadata_exact_db_fallback_enabled=settings.DIFY_EXTERNAL_KNOWLEDGE_METADATA_EXACT_DB_FALLBACK_ENABLED,
        retrieval_overfetch_multiplier=overfetch_multiplier,
        retrieval_overfetch_max_k=overfetch_max_k,
        enable_kg_query_expansion=kg_query_expansion_enabled,
        enable_kg_chunk_injection=kg_chunk_injection_enabled,
        kg_chunk_injection_max_chunks=(
            anchor_strength._dify_kg_int("DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_INJECTION_MAX_CHUNKS", 3)
            if kg_chunk_injection_max_chunks is None
            else int(kg_chunk_injection_max_chunks)
        ),
        enable_kg_chunk_boost=kg_chunk_boost_enabled,
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

    scoped_dataset_ids = common._dedupe_dataset_ids(list(dataset_ids or []))
    evidence_request_kwargs: dict[str, Any] = {"query": query, "rag_config": rag_config}
    evidence_request_kwargs["dataset_ids"] = scoped_dataset_ids

    response = await evidence_retrieval.retrieve_evidence(
        body=EvidenceRetrieveRequest(**evidence_request_kwargs),
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
