"""
Retrieval config fingerprint endpoint.

Provides a stable hash for effective retrieval knobs so external tooling can
pin runs and compare behavior across environments.
"""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies import get_current_account_id, get_tenant_id
from app.api.schemas.conversations import ChatRAGConfig
from app.api.utils import DEFAULT_HTTP_EXCEPTION_RESPONSES as _DEFAULT_HTTP_EXCEPTION_RESPONSES
from app.core.config import settings
from app.rag.core.retrieval_config_fingerprint import build_retrieval_config_fingerprint

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)

_SCHEMA = "mimirq.retrieval_config_hash.v1"


class RetrievalConfigHashRequest(BaseModel):
    rag_config: ChatRAGConfig = Field(default_factory=ChatRAGConfig)
    include_runtime_defaults: bool = True


class RetrievalConfigHashResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_: str = Field(default=_SCHEMA, alias="schema", serialization_alias="schema")
    hash: str
    fingerprint: dict[str, Any] = Field(default_factory=dict)
    effective_config: dict[str, Any] = Field(default_factory=dict)

    @property
    def schema(self) -> str:
        return self.schema_


def _runtime_flags() -> dict[str, Any]:
    return {
        "vector_backend": settings.VECTOR_BACKEND,
        "fusion_strategy": settings.RETRIEVAL_FUSION_STRATEGY,
        "reranker_provider_default": settings.RERANKER_PROVIDER,
        "bm25_enabled": settings.BM25_INDEX_ENABLED,
        "lexical_enabled": settings.LEXICAL_DB_TRGM_ENABLED,
        "sparse_enabled": settings.SPARSE_RETRIEVAL_ENABLED,
        "colbert_enabled": settings.COLBERT_RETRIEVAL_ENABLED,
        "evidence_post_rerank_enabled": settings.EVIDENCE_POST_RERANK_ENABLED,
        "hierarchy_recall_enabled": settings.HIERARCHY_RECALL_ENABLED,
        "hierarchy_family_collapse": settings.HIERARCHY_RECALL_FAMILY_COLLAPSE,
        "hierarchy_family_aggregation": settings.HIERARCHY_RECALL_FAMILY_AGGREGATION,
        "hierarchy_tree_dedup": settings.HIERARCHY_RECALL_TREE_DEDUP,
        "hierarchy_parent_depth": settings.HIERARCHY_RECALL_PARENT_DEPTH,
        "hierarchy_sibling_window": settings.HIERARCHY_RECALL_SIBLING_WINDOW,
        "hierarchy_overfetch_factor": settings.HIERARCHY_RECALL_OVERFETCH_FACTOR,
    }


def _effective_config(*, rag_config: ChatRAGConfig, include_runtime_defaults: bool) -> dict[str, Any]:
    hierarchy_enabled = (
        settings.HIERARCHY_RECALL_ENABLED
        if rag_config.enable_hierarchy_recall is None
        else rag_config.enable_hierarchy_recall
    )
    hierarchy_family_collapse = (
        settings.HIERARCHY_RECALL_FAMILY_COLLAPSE
        if rag_config.hierarchy_family_collapse is None
        else rag_config.hierarchy_family_collapse
    )
    hierarchy_family_aggregation = (
        settings.HIERARCHY_RECALL_FAMILY_AGGREGATION.strip().lower()
        if rag_config.hierarchy_family_aggregation is None
        else rag_config.hierarchy_family_aggregation
    )
    hierarchy_tree_dedup = (
        settings.HIERARCHY_RECALL_TREE_DEDUP
        if rag_config.hierarchy_tree_dedup is None
        else rag_config.hierarchy_tree_dedup
    )
    hierarchy_parent_depth = (
        settings.HIERARCHY_RECALL_PARENT_DEPTH
        if rag_config.hierarchy_parent_depth is None
        else rag_config.hierarchy_parent_depth
    )
    hierarchy_sibling_window = (
        settings.HIERARCHY_RECALL_SIBLING_WINDOW
        if rag_config.hierarchy_sibling_window is None
        else rag_config.hierarchy_sibling_window
    )
    hierarchy_overfetch_factor = (
        settings.HIERARCHY_RECALL_OVERFETCH_FACTOR
        if rag_config.hierarchy_overfetch_factor is None
        else rag_config.hierarchy_overfetch_factor
    )

    effective_config: dict[str, Any] = {
        "retrieval_profile": rag_config.retrieval_profile,
        "retrieval_mode": rag_config.retrieval_mode,
        "top_k": rag_config.top_k,
        "score_threshold": rag_config.score_threshold,
        "alpha": rag_config.alpha,
        "fusion_strategy": rag_config.fusion_strategy,
        "fusion_budgets": rag_config.fusion_budgets,
        "fusion_min_scores": rag_config.fusion_min_scores,
        "fusion_weights": rag_config.fusion_weights,
        "enable_weight_rerank": rag_config.enable_weight_rerank,
        "vector_weight": rag_config.vector_weight,
        "keyword_weight": rag_config.keyword_weight,
        "mmr_lambda": rag_config.mmr_lambda,
        "enable_reranker": rag_config.enable_reranker,
        "reranker_provider": rag_config.reranker_provider,
        "reranker_top_n": rag_config.reranker_top_n,
        "enable_multi_query": rag_config.enable_multi_query,
        "multi_query_count": rag_config.multi_query_count,
        "enable_hyde": rag_config.enable_hyde,
        "enable_query_rewrite": settings.ENABLE_QUERY_REWRITE,
        "query_rewrite_strategy": settings.QUERY_REWRITE_STRATEGY,
        "sparse_retrieval_enabled": rag_config.sparse_retrieval_enabled,
        "sparse_retrieval_provider": rag_config.sparse_retrieval_provider,
        "enable_hierarchy_recall": hierarchy_enabled,
        "hierarchy_family_collapse": hierarchy_family_collapse,
        "hierarchy_family_aggregation": hierarchy_family_aggregation,
        "hierarchy_tree_dedup": hierarchy_tree_dedup,
        "hierarchy_parent_depth": hierarchy_parent_depth,
        "hierarchy_sibling_window": hierarchy_sibling_window,
        "hierarchy_overfetch_factor": hierarchy_overfetch_factor,
        "visible_evidence_only": rag_config.visible_evidence_only,
    }
    if include_runtime_defaults:
        effective_config["runtime_defaults"] = _runtime_flags()
    return effective_config


@router.post("/config-hash")
async def get_retrieval_config_hash(
    body: RetrievalConfigHashRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],  # noqa: ARG001 - dependency enforces tenant context.
    account_id: Annotated[str, Depends(get_current_account_id)],  # noqa: ARG001 - dependency enforces account context.
) -> RetrievalConfigHashResponse:
    effective = _effective_config(
        rag_config=body.rag_config,
        include_runtime_defaults=body.include_runtime_defaults,
    )
    fingerprint = build_retrieval_config_fingerprint(config=effective)
    return RetrievalConfigHashResponse(
        schema=_SCHEMA,
        hash=fingerprint["hash"],
        fingerprint=fingerprint,
        effective_config=effective,
    )


__all__ = [
    "RetrievalConfigHashRequest",
    "RetrievalConfigHashResponse",
    "get_retrieval_config_hash",
    "router",
]
