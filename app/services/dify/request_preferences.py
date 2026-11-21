"""Dify request preferences operations."""

from fastapi import HTTPException

from app.api.schemas.integrations import DifyRetrievalSetting
from app.infrastructure.config import settings
from app.rag.retrieval.ranking.policy_rules import resolve_internal_candidate_top_k
from app.types.dify_integration import DifyKGFlags as _DifyKGFlags


def _resolve_internal_candidate_top_k(requested_top_k: int) -> int:
    return resolve_internal_candidate_top_k(
        requested_top_k,
        minimum=settings.DIFY_EXTERNAL_KNOWLEDGE_INTERNAL_TOP_K_MIN,
        multiplier=settings.DIFY_EXTERNAL_KNOWLEDGE_INTERNAL_TOP_K_MULTIPLIER,
        maximum=settings.DIFY_EXTERNAL_KNOWLEDGE_INTERNAL_TOP_K_MAX,
    )


def _resolve_mixed_intent_subquery_top_k(*, response_top_k: int, candidate_top_k: int) -> int:
    # A configured zero delegates the limit to the requested response size.
    configured = settings.DIFY_EXTERNAL_KNOWLEDGE_MIXED_INTENT_SUBQUERY_TOP_K or response_top_k
    return max(1, min(candidate_top_k, configured))


def _disabled_dify_kg_flags() -> _DifyKGFlags:
    return _DifyKGFlags(
        enable_query_expansion=False,
        enable_chunk_injection=False,
        chunk_injection_max_chunks=0,
        enable_chunk_boost=False,
        chunk_boost_weight=0.0,
        chunk_boost_max_promoted=0,
    )


def _resolve_dify_kg_flags(setting: DifyRetrievalSetting) -> _DifyKGFlags:
    return _DifyKGFlags(
        enable_query_expansion=(
            settings.DIFY_EXTERNAL_KNOWLEDGE_KG_QUERY_EXPANSION_ENABLED
            if setting.enable_kg_query_expansion is None
            else setting.enable_kg_query_expansion
        ),
        enable_chunk_injection=(
            settings.DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_INJECTION_ENABLED
            if setting.enable_kg_chunk_injection is None
            else setting.enable_kg_chunk_injection
        ),
        chunk_injection_max_chunks=(
            settings.DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_INJECTION_MAX_CHUNKS
            if setting.kg_chunk_injection_max_chunks is None
            else setting.kg_chunk_injection_max_chunks
        ),
        enable_chunk_boost=(
            settings.DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_BOOST_ENABLED
            if setting.enable_kg_chunk_boost is None
            else setting.enable_kg_chunk_boost
        ),
        chunk_boost_weight=(
            settings.DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_BOOST_WEIGHT
            if setting.kg_chunk_boost_weight is None
            else setting.kg_chunk_boost_weight
        ),
        chunk_boost_max_promoted=(
            settings.DIFY_EXTERNAL_KNOWLEDGE_KG_CHUNK_BOOST_MAX_PROMOTED
            if setting.kg_chunk_boost_max_promoted is None
            else setting.kg_chunk_boost_max_promoted
        ),
    )


def _resolve_dify_latency_profile(setting: DifyRetrievalSetting) -> str:
    if setting.latency_profile is None:
        return "quality"
    raw = setting.latency_profile.strip().lower().replace("-", "_")
    if not raw or raw in {"default", "quality", "standard"}:
        return "quality"
    if raw in {"fast", "low_latency", "online"}:
        return "fast"
    raise HTTPException(
        status_code=400,
        detail=f"Unsupported Dify retrieval latency_profile: {setting.latency_profile}",
    )
