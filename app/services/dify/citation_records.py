"""Dify citation records rules and operations."""

import logging
import time
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

import app.services.dify.answer_hints as answer_hints
import app.services.dify.chunk_hydration as chunk_hydration
import app.services.dify.query_policy as query_policy
from app.api.schemas.conversations import ChatRAGConfig
from app.infrastructure.config import settings
from app.services.dify.anchor_strength import _record_matches_requested_slot as _record_matches_requested_slot
from app.services.dify.common import _CONTENT_KEYS, _METADATA_KEYS, _TITLE_KEYS, _dedupe_dataset_ids
from app.services.dify.common import _citation_chunk_id as _citation_chunk_id
from app.services.dify.common import _citation_dataset_id as _citation_dataset_id
from app.services.dify.common import _citation_score as _citation_score
from app.services.dify.common import _first_non_empty as _first_non_empty
from app.services.dify.scoring import _diagnostic_query_hash

logger = logging.getLogger("app.services.dify_integration.citation_records")
_retrieval_logger = logging.getLogger("app.api.v1.integrations_dify")


def _citations_to_hydrate(
    citations: list[dict[str, Any]],
    *,
    query: str,
    policy_plugin_refs: tuple[str, ...],
) -> dict[int, dict[str, Any]]:
    requested_slots = None
    selected = {}
    for index, citation in enumerate(citations):
        content = _first_non_empty(citation, _CONTENT_KEYS)
        if not content:
            selected[index] = citation
            continue
        if "..." not in content and "…" not in content:
            continue
        if requested_slots is None:
            requested_slots = query_policy._requested_policy_slot_specs_for_query(
                query,
                policy_plugin_refs=policy_plugin_refs,
            )
        if not requested_slots:
            continue
        metadata = citation.get("metadata")
        record = {
            "content": content,
            "title": _first_non_empty(citation, _TITLE_KEYS),
            "metadata": metadata if isinstance(metadata, dict) else {},
        }
        if _record_matches_requested_slot(record, requested_slots):
            selected[index] = citation
    return selected


def _records_from_citations(
    *,
    db: Session,
    tenant_id: UUID,
    citations: list[dict[str, Any]],
    fallback_dataset_id: UUID | None,
    query: str,
    hydration_query: str | None = None,
    policy_plugin_refs: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    selected = _citations_to_hydrate(citations, query=hydration_query or query, policy_plugin_refs=policy_plugin_refs)
    chunk_content_map = {}
    if selected:
        chunk_content_map = chunk_hydration._load_chunk_content_map(
            db=db, tenant_id=tenant_id, citations=list(selected.values())
        )
    return _build_citation_records(
        citations,
        selected=selected,
        chunk_content_map=chunk_content_map,
        fallback_dataset_id=fallback_dataset_id,
        query=query,
        policy_plugin_refs=policy_plugin_refs,
    )


def _build_citation_records(
    citations: list[dict[str, Any]],
    *,
    selected: dict[int, dict[str, Any]],
    chunk_content_map: dict[str, str],
    fallback_dataset_id: UUID | None,
    query: str,
    policy_plugin_refs: tuple[str, ...],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for index, citation in enumerate(citations):
        if index in selected:
            chunk_id = _citation_chunk_id(citation)
            content = chunk_content_map.get(chunk_id) if chunk_id else None
            if content:
                citation = {**citation, "content": content}
        record = _citation_to_dify_record(
            citation,
            dataset_id=fallback_dataset_id,
            query=query,
            policy_plugin_refs=policy_plugin_refs,
        )
        if record["content"].strip():
            records.append(record)
    return records


async def _records_from_citations_with_managed_hydration(
    *,
    db: Session,
    tenant_id: UUID,
    citations: list[dict[str, Any]],
    fallback_dataset_id: UUID | None,
    query: str,
    hydration_query: str | None = None,
    policy_plugin_refs: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    selected = _citations_to_hydrate(citations, query=hydration_query or query, policy_plugin_refs=policy_plugin_refs)
    chunk_content_map: dict[str, str] = {}
    if selected:
        try:
            chunk_content_map = await chunk_hydration._offload_chunk_content_hydration(
                request_db=db,
                tenant_id=tenant_id,
                citations=list(selected.values()),
            )
        except Exception:  # noqa: BLE001
            logger.warning("Failed to hydrate Dify chunk content; falling back to citation snippets", exc_info=True)

    return _build_citation_records(
        citations,
        selected=selected,
        chunk_content_map=chunk_content_map,
        fallback_dataset_id=fallback_dataset_id,
        query=query,
        policy_plugin_refs=policy_plugin_refs,
    )


def _citation_to_dify_record(
    citation: dict[str, Any],
    *,
    dataset_id: UUID | None,
    query: str = "",
    policy_plugin_refs: tuple[str, ...] = (),
) -> dict[str, Any]:
    content = _first_non_empty(citation, _CONTENT_KEYS)
    title = _first_non_empty(citation, _TITLE_KEYS) or "Untitled"

    raw_metadata = citation.get("metadata")
    metadata: dict[str, Any] = (
        {key: value for key, value in raw_metadata.items() if key not in {"sparse_score", "colbert_score"}}
        if isinstance(raw_metadata, dict)
        else {}
    )
    resolved_dataset_id = _citation_dataset_id(citation, fallback_dataset_id=dataset_id)
    if resolved_dataset_id is not None:
        metadata["dataset_id"] = str(resolved_dataset_id)
    for key in _METADATA_KEYS:
        value = citation.get(key)
        if value is not None and value != "":
            metadata[key] = value
    if metadata.get("hit_type") in ("sparse", "colbert", "colbert_ann"):
        del metadata["hit_type"]
    content = answer_hints._content_with_answer_hints(
        content, metadata, query=query, policy_plugin_refs=policy_plugin_refs
    )

    return {
        "content": content,
        "score": _citation_score(citation),
        "title": title,
        "metadata": metadata,
    }


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
    from app.api.schemas.conversations import EvidenceRetrieveRequest
    from app.services.retrieval.requests import retrieve_evidence

    started = time.perf_counter()
    evidence_top_k = max(1, top_k)

    overfetch_multiplier = max(
        1,
        settings.DIFY_EXTERNAL_KNOWLEDGE_RETRIEVAL_OVERFETCH_MULTIPLIER,
    )
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
        retrieval_mode=retrieval_mode,
        visible_evidence_only=True,
        metadata_filter=metadata_filter,
        enable_reranker=enable_reranker,
        reranker_provider=settings.RERANKER_PROVIDER if enable_reranker else "none",
        reranker_top_n=reranker_top_n,
        lexical_db_hybrid_fallback_only=settings.DIFY_EXTERNAL_KNOWLEDGE_LEXICAL_DB_HYBRID_FALLBACK_ONLY,
        lexical_db_hybrid_metadata_exact_fallback_enabled=(
            settings.DIFY_EXTERNAL_KNOWLEDGE_LEXICAL_METADATA_EXACT_FALLBACK_ENABLED
        ),
        metadata_exact_db_fallback_enabled=settings.DIFY_EXTERNAL_KNOWLEDGE_METADATA_EXACT_DB_FALLBACK_ENABLED,
        retrieval_overfetch_multiplier=overfetch_multiplier,
        retrieval_overfetch_max_k=overfetch_max_k,
        enable_kg_query_expansion=enable_kg_query_expansion,
        enable_kg_chunk_injection=enable_kg_chunk_injection,
        kg_chunk_injection_max_chunks=(
            settings.DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_INJECTION_MAX_CHUNKS
            if kg_chunk_injection_max_chunks is None
            else kg_chunk_injection_max_chunks
        ),
        enable_kg_chunk_boost=enable_kg_chunk_boost,
        kg_chunk_boost_weight=(
            settings.DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_BOOST_WEIGHT
            if kg_chunk_boost_weight is None
            else kg_chunk_boost_weight
        ),
        kg_chunk_boost_max_promoted=(
            settings.DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_BOOST_MAX_PROMOTED
            if kg_chunk_boost_max_promoted is None
            else kg_chunk_boost_max_promoted
        ),
    )

    scoped_dataset_ids = _dedupe_dataset_ids(dataset_ids)
    response = await retrieve_evidence(
        body=EvidenceRetrieveRequest(query=query, rag_config=rag_config, dataset_ids=scoped_dataset_ids),
        tenant_id=tenant_id,
        account_id=account_id,
        db=db,
    )
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    metrics = response.metrics
    trace = response.retrieval_trace or {}
    _retrieval_logger.info(
        "Dify evidence retrieve completed query_hash=%s dataset_count=%s top_k=%s requested_top_k=%s "
        "citations=%s elapsed_ms=%s retrieval_elapsed_sec=%s vector_backend=%s retrieval_mode=%s "
        "post_rerank_elapsed_sec=%s hard_fallback_elapsed_sec=%s trace_passes=%s",
        _diagnostic_query_hash(query),
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
        len(trace.get("passes") or []),
    )
    return list(response.citations)
