"""
Single-query retrieval explain endpoint.

Returns a deterministic retrieval-only explain payload so contributors can
diagnose recall/rerank behavior without running the full chat flow.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.chat import ChatRAGConfig, HistoryMessage
from app.api.v1.rag import _enforce_non_empty_retrieval_scope
from app.core.config import settings
from app.core.database import get_db
from app.rag.pipelines.langgraph import build_rag_state
from app.rag.retrieval.orchestrator import run_retrieval
from app.services.dataset_service import DatasetService
from app.services.document_access import filter_allowed_document_ids

_DEFAULT_HTTP_EXCEPTION_RESPONSES = {
    400: {"description": "Bad Request"},
    403: {"description": "Forbidden"},
    404: {"description": "Not Found"},
    409: {"description": "Conflict"},
    416: {"description": "Range Not Satisfiable"},
}

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)

_SCHEMA = "mimirq.retrieval_explain.v1"


class RetrievalExplainRequest(BaseModel):
    query: str = Field(min_length=1)
    history: list[HistoryMessage] = Field(default_factory=list)
    dataset_id: UUID | None = None
    document_ids: list[UUID] = Field(default_factory=list)
    rag_config: ChatRAGConfig = Field(default_factory=ChatRAGConfig)
    retrieval_only: bool = True
    top_citations_limit: int = Field(default=5, ge=1, le=20)


class RetrievalExplainResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_: str = Field(default=_SCHEMA, alias="schema", serialization_alias="schema")
    retrieval_only: bool = True
    query_for_retrieval: str
    channels: dict[str, Any] = Field(default_factory=dict)
    hierarchy_recall: dict[str, Any] = Field(default_factory=dict)
    candidate_counts: dict[str, int] = Field(default_factory=dict)
    top_citations: list[dict[str, Any]] = Field(default_factory=list)
    rerank: dict[str, Any] = Field(default_factory=dict)
    stage_timings: dict[str, float] = Field(default_factory=dict)
    metrics: dict[str, Any] = Field(default_factory=dict)
    query_debug: dict[str, Any] = Field(default_factory=dict)
    retrieval_trace: dict[str, Any] = Field(default_factory=dict)

    @property
    def schema(self) -> str:
        return str(self.schema_)


def _trim_top_citation(row: Any) -> dict[str, Any]:
    item = row if isinstance(row, dict) else {}
    out = {
        "chunk_id": item.get("chunk_id"),
        "document_id": item.get("document_id"),
        "source": item.get("source"),
        "retrieval_role": item.get("retrieval_role"),
        "relevance_score": item.get("relevance_score"),
        "retrieval_score": item.get("retrieval_score"),
        "rerank_score": item.get("rerank_score"),
        "rerank_score_calibrated": item.get("rerank_score_calibrated"),
    }
    return {k: v for k, v in out.items() if v is not None}


def _as_history_dicts(history: list[HistoryMessage]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for msg in history or []:
        if hasattr(msg, "model_dump"):
            payload = msg.model_dump()
        elif isinstance(msg, dict):
            payload = dict(msg)
        else:
            payload = {}
        out.append(
            {
                "role": str(payload.get("role") or ""),
                "content": str(payload.get("content") or ""),
            }
        )
    return out


@router.post("/explain", responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)
async def explain_retrieval(
    body: RetrievalExplainRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> RetrievalExplainResponse:
    if not bool(body.retrieval_only):
        raise HTTPException(status_code=400, detail="retrieval_only must be true for this endpoint")

    DatasetService.ensure_member(db, tenant_id, account_id)

    scope_dataset_id: UUID | None = None
    scope_document_ids: list[UUID] = []
    if body.document_ids:
        scope_document_ids = filter_allowed_document_ids(db, tenant_id, account_id, body.document_ids)
    elif body.dataset_id is not None:
        ds = DatasetService.get_dataset(db, tenant_id, body.dataset_id)
        DatasetService.assert_dataset_readable(db, ds, account_id)
        scope_dataset_id = body.dataset_id
    elif not bool(getattr(settings, "CHAT_ALLOW_OPEN_SCOPE", False)):
        raise HTTPException(status_code=400, detail="dataset_id is required when document_ids is empty")

    _enforce_non_empty_retrieval_scope(
        db,
        tenant_id=tenant_id,
        account_id=account_id,
        scope_document_ids=scope_document_ids,
        scope_dataset_id=scope_dataset_id,
    )

    request_fields_set = set(getattr(body, "model_fields_set", set()) or set())
    rag_config_provided = "rag_config" in request_fields_set
    effective_rag_config = body.rag_config if rag_config_provided else ChatRAGConfig(retrieval_profile="recall50")

    state = build_rag_state(
        question=body.query,
        history=_as_history_dicts(body.history),
        document_ids=scope_document_ids,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=scope_dataset_id,
        top_k=effective_rag_config.top_k,
        score_threshold=effective_rag_config.score_threshold,
        retrieval_mode=effective_rag_config.retrieval_mode,
        retrieval_profile=effective_rag_config.retrieval_profile,
        intent_router=effective_rag_config.intent_router,
        intent_router_policy=effective_rag_config.intent_router_policy,
        enable_query_alias_expansion=effective_rag_config.enable_query_alias_expansion,
        query_aliases=effective_rag_config.query_aliases,
        query_alias_max_queries=effective_rag_config.query_alias_max_queries,
        enable_multi_query=effective_rag_config.enable_multi_query,
        multi_query_count=effective_rag_config.multi_query_count,
        multi_query_temperature=effective_rag_config.multi_query_temperature,
        multi_query_max_chars=effective_rag_config.multi_query_max_chars,
        enable_hyde=effective_rag_config.enable_hyde,
        enable_query_decomposition=effective_rag_config.enable_query_decomposition,
        enable_hierarchy_recall=effective_rag_config.enable_hierarchy_recall,
        hierarchy_family_collapse=effective_rag_config.hierarchy_family_collapse,
        hierarchy_family_aggregation=effective_rag_config.hierarchy_family_aggregation,
        hierarchy_tree_dedup=effective_rag_config.hierarchy_tree_dedup,
        hierarchy_parent_depth=effective_rag_config.hierarchy_parent_depth,
        hierarchy_sibling_window=effective_rag_config.hierarchy_sibling_window,
        hierarchy_overfetch_factor=effective_rag_config.hierarchy_overfetch_factor,
        enable_query_rewrite=getattr(effective_rag_config, "enable_query_rewrite", None),
        query_rewrite_strategy=getattr(effective_rag_config, "query_rewrite_strategy", None),
        query_rewrite_temperature=getattr(effective_rag_config, "query_rewrite_temperature", None),
        query_rewrite_max_chars=getattr(effective_rag_config, "query_rewrite_max_chars", None),
        sparse_retrieval_enabled=getattr(effective_rag_config, "sparse_retrieval_enabled", None),
        sparse_retrieval_provider=getattr(effective_rag_config, "sparse_retrieval_provider", None),
        alpha=effective_rag_config.alpha,
        fusion_strategy=effective_rag_config.fusion_strategy,
        fusion_budgets=effective_rag_config.fusion_budgets,
        fusion_min_scores=effective_rag_config.fusion_min_scores,
        fusion_weights=effective_rag_config.fusion_weights,
        enable_weight_rerank=effective_rag_config.enable_weight_rerank,
        vector_weight=effective_rag_config.vector_weight,
        keyword_weight=effective_rag_config.keyword_weight,
        mmr_lambda=effective_rag_config.mmr_lambda,
        enable_reranker=effective_rag_config.enable_reranker,
        reranker_provider=effective_rag_config.reranker_provider,
        reranker_top_n=effective_rag_config.reranker_top_n,
        metadata_filter=effective_rag_config.metadata_filter,
        visible_evidence_only=effective_rag_config.visible_evidence_only,
        db=db,
    )
    out = run_retrieval(state)

    citations = out.get("citations") if isinstance(out.get("citations"), list) else []
    metrics = out.get("metrics") if isinstance(out.get("metrics"), dict) else {}
    query_debug = out.get("query_debug") if isinstance(out.get("query_debug"), dict) else {}
    retrieval_trace = out.get("retrieval_trace") if isinstance(out.get("retrieval_trace"), dict) else {}

    channels = query_debug.get("channels") if isinstance(query_debug.get("channels"), dict) else {}
    hierarchy_recall = query_debug.get("hierarchy_recall") if isinstance(query_debug.get("hierarchy_recall"), dict) else {}
    if not hierarchy_recall:
        hierarchy_recall = retrieval_trace.get("hierarchy_recall") if isinstance(retrieval_trace.get("hierarchy_recall"), dict) else {}
    query_count = int(metrics.get("retrieval_query_count") or len(metrics.get("retrieval_per_query") or []))
    top_limit = max(1, int(body.top_citations_limit or 1))

    stage_timings = {
        "retrieval_elapsed_sec": float(metrics.get("retrieval_elapsed_sec") or 0.0),
        "rewrite_elapsed_sec": float(metrics.get("rewrite_elapsed_sec") or 0.0),
        "multi_query_elapsed_sec": float(metrics.get("multi_query_elapsed_sec") or 0.0),
        "decompose_elapsed_sec": float(metrics.get("decompose_elapsed_sec") or 0.0),
        "post_rerank_elapsed_sec": float(metrics.get("evidence_post_rerank_elapsed_sec") or 0.0),
    }

    rerank_meta = {
        "provider": metrics.get("evidence_post_rerank_provider"),
        "used": bool(metrics.get("evidence_post_rerank_used")),
        "candidates_n": int(metrics.get("evidence_post_rerank_candidates_n") or 0),
        "pipeline_stages": (
            list(metrics.get("evidence_post_rerank_pipeline_stages") or [])
            if isinstance(metrics.get("evidence_post_rerank_pipeline_stages"), list)
            else []
        ),
        "cache_hits": int(metrics.get("evidence_post_rerank_cache_hits") or 0),
        "cache_misses": int(metrics.get("evidence_post_rerank_cache_misses") or 0),
    }

    return RetrievalExplainResponse(
        schema=_SCHEMA,
        retrieval_only=True,
        query_for_retrieval=str(out.get("query_for_retrieval") or body.query),
        channels=channels,
        hierarchy_recall=hierarchy_recall,
        candidate_counts={
            "query_count": query_count,
            "citations": len(citations),
        },
        top_citations=[_trim_top_citation(row) for row in citations[:top_limit]],
        rerank=rerank_meta,
        stage_timings=stage_timings,
        metrics=metrics,
        query_debug=query_debug,
        retrieval_trace=retrieval_trace,
    )


__all__ = [
    "RetrievalExplainRequest",
    "RetrievalExplainResponse",
    "explain_retrieval",
    "router",
]
