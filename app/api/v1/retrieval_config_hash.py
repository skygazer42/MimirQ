"""
Retrieval config fingerprint endpoint.

Provides a stable hash for effective retrieval knobs so external tooling can
pin runs and compare behavior across environments.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.chat import ChatRAGConfig
from app.core.config import settings
from app.rag.core.retrieval_config_fingerprint import build_retrieval_config_fingerprint

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

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
        return str(self.schema_)


def _runtime_flags() -> dict[str, Any]:
    return {
        "vector_backend": str(getattr(settings, "VECTOR_BACKEND", "milvus") or "milvus"),
        "fusion_strategy": str(getattr(settings, "RETRIEVAL_FUSION_STRATEGY", "linear") or "linear"),
        "reranker_provider_default": str(getattr(settings, "RERANKER_PROVIDER", "llm") or "llm"),
        "bm25_enabled": bool(getattr(settings, "BM25_INDEX_ENABLED", False)),
        "lexical_enabled": bool(getattr(settings, "LEXICAL_DB_TRGM_ENABLED", False)),
        "sparse_enabled": bool(getattr(settings, "SPARSE_RETRIEVAL_ENABLED", False)),
        "colbert_enabled": bool(getattr(settings, "COLBERT_RETRIEVAL_ENABLED", False)),
        "evidence_post_rerank_enabled": bool(getattr(settings, "EVIDENCE_POST_RERANK_ENABLED", False)),
        "hierarchy_recall_enabled": bool(getattr(settings, "HIERARCHY_RECALL_ENABLED", False)),
        "hierarchy_family_collapse": bool(getattr(settings, "HIERARCHY_RECALL_FAMILY_COLLAPSE", False)),
        "hierarchy_family_aggregation": str(
            getattr(settings, "HIERARCHY_RECALL_FAMILY_AGGREGATION", "combined") or "combined"
        ),
        "hierarchy_tree_dedup": bool(getattr(settings, "HIERARCHY_RECALL_TREE_DEDUP", False)),
        "hierarchy_parent_depth": int(getattr(settings, "HIERARCHY_RECALL_PARENT_DEPTH", 0) or 0),
        "hierarchy_sibling_window": int(getattr(settings, "HIERARCHY_RECALL_SIBLING_WINDOW", 0) or 0),
        "hierarchy_overfetch_factor": int(getattr(settings, "HIERARCHY_RECALL_OVERFETCH_FACTOR", 4) or 4),
    }


def _effective_config(*, rag_config: ChatRAGConfig, include_runtime_defaults: bool) -> dict[str, Any]:
    hierarchy_enabled = (
        bool(getattr(settings, "HIERARCHY_RECALL_ENABLED", False))
        if rag_config.enable_hierarchy_recall is None
        else bool(rag_config.enable_hierarchy_recall)
    )
    hierarchy_family_collapse = (
        bool(getattr(settings, "HIERARCHY_RECALL_FAMILY_COLLAPSE", False))
        if rag_config.hierarchy_family_collapse is None
        else bool(rag_config.hierarchy_family_collapse)
    )
    hierarchy_family_aggregation = (
        str(getattr(settings, "HIERARCHY_RECALL_FAMILY_AGGREGATION", "combined") or "combined").strip().lower()
        if rag_config.hierarchy_family_aggregation is None
        else str(rag_config.hierarchy_family_aggregation or "").strip().lower()
    )
    hierarchy_tree_dedup = (
        bool(getattr(settings, "HIERARCHY_RECALL_TREE_DEDUP", False))
        if rag_config.hierarchy_tree_dedup is None
        else bool(rag_config.hierarchy_tree_dedup)
    )
    hierarchy_parent_depth = (
        int(getattr(settings, "HIERARCHY_RECALL_PARENT_DEPTH", 0) or 0)
        if rag_config.hierarchy_parent_depth is None
        else int(rag_config.hierarchy_parent_depth or 0)
    )
    hierarchy_sibling_window = (
        int(getattr(settings, "HIERARCHY_RECALL_SIBLING_WINDOW", 0) or 0)
        if rag_config.hierarchy_sibling_window is None
        else int(rag_config.hierarchy_sibling_window or 0)
    )
    hierarchy_overfetch_factor = (
        int(getattr(settings, "HIERARCHY_RECALL_OVERFETCH_FACTOR", 4) or 4)
        if rag_config.hierarchy_overfetch_factor is None
        else int(rag_config.hierarchy_overfetch_factor or 0)
    )

    cfg: dict[str, Any] = {
        "retrieval_profile": rag_config.retrieval_profile,
        "retrieval_mode": rag_config.retrieval_mode,
        "top_k": int(rag_config.top_k or 0),
        "score_threshold": float(rag_config.score_threshold or 0.0),
        "alpha": float(rag_config.alpha or 0.0),
        "fusion_strategy": rag_config.fusion_strategy,
        "fusion_budgets": rag_config.fusion_budgets,
        "fusion_min_scores": rag_config.fusion_min_scores,
        "fusion_weights": rag_config.fusion_weights,
        "enable_weight_rerank": bool(rag_config.enable_weight_rerank),
        "vector_weight": float(rag_config.vector_weight or 0.0),
        "keyword_weight": float(rag_config.keyword_weight or 0.0),
        "mmr_lambda": float(rag_config.mmr_lambda or 0.0),
        "enable_reranker": bool(rag_config.enable_reranker),
        "reranker_provider": rag_config.reranker_provider,
        "reranker_top_n": int(rag_config.reranker_top_n or 0),
        "enable_multi_query": getattr(rag_config, "enable_multi_query", None),
        "multi_query_count": getattr(rag_config, "multi_query_count", None),
        "enable_query_rewrite": getattr(rag_config, "enable_query_rewrite", None),
        "query_rewrite_strategy": getattr(rag_config, "query_rewrite_strategy", None),
        "sparse_retrieval_enabled": getattr(rag_config, "sparse_retrieval_enabled", None),
        "sparse_retrieval_provider": getattr(rag_config, "sparse_retrieval_provider", None),
        "enable_hierarchy_recall": bool(hierarchy_enabled),
        "hierarchy_family_collapse": bool(hierarchy_family_collapse),
        "hierarchy_family_aggregation": hierarchy_family_aggregation or "combined",
        "hierarchy_tree_dedup": bool(hierarchy_tree_dedup),
        "hierarchy_parent_depth": int(hierarchy_parent_depth),
        "hierarchy_sibling_window": int(hierarchy_sibling_window),
        "hierarchy_overfetch_factor": int(hierarchy_overfetch_factor),
        "visible_evidence_only": bool(rag_config.visible_evidence_only),
    }
    if include_runtime_defaults:
        cfg["runtime_defaults"] = _runtime_flags()
    return cfg


@router.post("/config-hash", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def get_retrieval_config_hash(
    body: RetrievalConfigHashRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],  # noqa: ARG001 - dependency enforces tenant context.
    account_id: Annotated[str, Depends(get_current_account_id)],  # noqa: ARG001 - dependency enforces account context.
) -> RetrievalConfigHashResponse:
    effective = _effective_config(
        rag_config=body.rag_config,
        include_runtime_defaults=bool(body.include_runtime_defaults),
    )
    fp = build_retrieval_config_fingerprint(config=effective)
    return RetrievalConfigHashResponse(
        schema=_SCHEMA,
        hash=str(fp.get("hash") or ""),
        fingerprint=fp,
        effective_config=effective,
    )


__all__ = [
    "RetrievalConfigHashRequest",
    "RetrievalConfigHashResponse",
    "get_retrieval_config_hash",
    "router",
]
