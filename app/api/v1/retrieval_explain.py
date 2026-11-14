"""
Single-query retrieval explain endpoint.

Returns a deterministic retrieval-only explain payload so contributors can
diagnose recall/rerank behavior without running the full chat flow.
"""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_account_id, get_tenant_id
from app.api.schemas.conversations import ChatRAGConfig, HistoryMessage
from app.api.utils import DEFAULT_HTTP_EXCEPTION_RESPONSES as _DEFAULT_HTTP_EXCEPTION_RESPONSES
from app.core.config import settings
from app.core.database import get_db
from app.rag.pipelines.langgraph import build_rag_state
from app.rag.retrieval.orchestrator import run_retrieval
from app.services import dataset_service
from app.services.rag_runtime_limiter import (
    run_blocking_call_with_managed_session,
    run_blocking_retrieval_call_with_managed_session,
)
from app.services.retrieval_scope import _resolve_retrieval_scope

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)

_SCHEMA = "mimirq.retrieval_explain.v1"


class RetrievalExplainRequest(BaseModel):
    query: str = Field(min_length=1, max_length=settings.RETRIEVAL_QUERY_MAX_CHARS)
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
    retrieval_degraded: bool = False
    fallback_reason: str | None = None
    channel_health: dict[str, Any] = Field(default_factory=dict)
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
        return self.schema_


def _trim_top_citation(citation: dict[str, Any]) -> dict[str, Any]:
    public_fields = {
        "chunk_id": citation.get("chunk_id"),
        "document_id": citation.get("document_id"),
        "source": citation.get("source"),
        "retrieval_role": citation.get("retrieval_role"),
        "relevance_score": citation.get("relevance_score"),
        "retrieval_score": citation.get("retrieval_score"),
        "rerank_score": citation.get("rerank_score"),
        "rerank_score_calibrated": citation.get("rerank_score_calibrated"),
    }
    return {name: value for name, value in public_fields.items() if value is not None}


@router.post("/explain")
async def explain_retrieval(
    body: RetrievalExplainRequest,
    *,
    tenant_id: Annotated[UUID, Depends(get_tenant_id)],
    account_id: Annotated[str, Depends(get_current_account_id)],
    db: Annotated[Session, Depends(get_db)],
) -> RetrievalExplainResponse:
    if not body.retrieval_only:
        raise HTTPException(status_code=400, detail="retrieval_only must be true for this endpoint")

    rag_config = body.rag_config

    def prepare_request(worker_db: Session) -> dict[str, Any]:
        dataset_service.ensure_member(worker_db, tenant_id, account_id)
        scope_dataset_id, _scope_dataset_ids, scope_document_ids = _resolve_retrieval_scope(
            db=worker_db,
            tenant_id=tenant_id,
            account_id=account_id,
            document_ids=body.document_ids,
            dataset_id=body.dataset_id,
        )
        return build_rag_state(
            question=body.query,
            history=[{"role": message.role, "content": message.content} for message in body.history],
            document_ids=scope_document_ids,
            tenant_id=tenant_id,
            account_id=account_id,
            dataset_id=scope_dataset_id,
            top_k=rag_config.top_k,
            score_threshold=rag_config.score_threshold,
            retrieval_mode=rag_config.retrieval_mode,
            retrieval_profile=rag_config.retrieval_profile,
            intent_router=rag_config.intent_router,
            intent_router_policy=rag_config.intent_router_policy,
            enable_query_alias_expansion=rag_config.enable_query_alias_expansion,
            query_aliases=rag_config.query_aliases,
            query_alias_max_queries=rag_config.query_alias_max_queries,
            enable_multi_query=rag_config.enable_multi_query,
            multi_query_count=rag_config.multi_query_count,
            multi_query_temperature=rag_config.multi_query_temperature,
            multi_query_max_chars=rag_config.multi_query_max_chars,
            enable_hyde=rag_config.enable_hyde,
            enable_query_decomposition=rag_config.enable_query_decomposition,
            enable_hierarchy_recall=rag_config.enable_hierarchy_recall,
            hierarchy_family_collapse=rag_config.hierarchy_family_collapse,
            hierarchy_family_aggregation=rag_config.hierarchy_family_aggregation,
            hierarchy_tree_dedup=rag_config.hierarchy_tree_dedup,
            hierarchy_parent_depth=rag_config.hierarchy_parent_depth,
            hierarchy_sibling_window=rag_config.hierarchy_sibling_window,
            hierarchy_overfetch_factor=rag_config.hierarchy_overfetch_factor,
            enable_kg_query_expansion=rag_config.enable_kg_query_expansion,
            enable_kg_chunk_injection=rag_config.enable_kg_chunk_injection,
            kg_chunk_injection_max_chunks=rag_config.kg_chunk_injection_max_chunks,
            enable_kg_chunk_boost=rag_config.enable_kg_chunk_boost,
            kg_chunk_boost_weight=rag_config.kg_chunk_boost_weight,
            kg_chunk_boost_max_promoted=rag_config.kg_chunk_boost_max_promoted,
            sparse_retrieval_enabled=rag_config.sparse_retrieval_enabled,
            sparse_retrieval_provider=rag_config.sparse_retrieval_provider,
            alpha=rag_config.alpha,
            fusion_strategy=rag_config.fusion_strategy,
            fusion_budgets=rag_config.fusion_budgets,
            fusion_min_scores=rag_config.fusion_min_scores,
            fusion_weights=rag_config.fusion_weights,
            enable_weight_rerank=rag_config.enable_weight_rerank,
            vector_weight=rag_config.vector_weight,
            keyword_weight=rag_config.keyword_weight,
            mmr_lambda=rag_config.mmr_lambda,
            enable_reranker=rag_config.enable_reranker,
            reranker_provider=rag_config.reranker_provider,
            reranker_top_n=rag_config.reranker_top_n,
            metadata_filter=rag_config.metadata_filter,
            visible_evidence_only=rag_config.visible_evidence_only,
        )

    state = await run_blocking_call_with_managed_session(prepare_request, request_db=None)
    offload_metrics: dict[str, Any] = {}
    out = await run_blocking_retrieval_call_with_managed_session(
        lambda worker_db: run_retrieval({**state, "db": worker_db}),
        request_db=db,
        runtime_metrics=offload_metrics,
    )

    citations = out["citations"]
    metrics = dict(out["metrics"])
    metrics.update(offload_metrics)
    query_debug = out["query_debug"]
    retrieval_trace = out["retrieval_trace"]

    # Retrieval bypass omits these diagnostics and explicitly sets channels to None.
    channels = query_debug.get("channels")
    channel_health = out.get("channel_health")
    if not channel_health:
        channel_health = metrics.get("retrieval_channel_health", {})
    hierarchy_recall = query_debug.get("hierarchy_recall")
    if not hierarchy_recall:
        hierarchy_recall = retrieval_trace.get("hierarchy_recall", {})

    stage_timings = {
        "retrieval_elapsed_sec": metrics.get("retrieval_elapsed_sec", 0.0),
        "rewrite_elapsed_sec": metrics.get("rewrite_elapsed_sec", 0.0),
        "multi_query_elapsed_sec": metrics.get("multi_query_elapsed_sec", 0.0),
        "decompose_elapsed_sec": metrics.get("decompose_elapsed_sec", 0.0),
        "post_rerank_elapsed_sec": metrics.get("evidence_post_rerank_elapsed_sec", 0.0),
    }

    rerank_meta = {
        "provider": metrics.get("evidence_post_rerank_provider"),
        "used": metrics.get("evidence_post_rerank_used", False),
        "candidates_n": metrics.get("evidence_post_rerank_candidates_n", 0),
        "pipeline_stages": metrics.get("evidence_post_rerank_pipeline_stages", []),
        "cache_hits": metrics.get("evidence_post_rerank_cache_hits", 0),
        "cache_misses": metrics.get("evidence_post_rerank_cache_misses", 0),
    }

    return RetrievalExplainResponse(
        schema=_SCHEMA,
        retrieval_only=True,
        query_for_retrieval=out["query_for_retrieval"] or body.query,
        retrieval_degraded=out.get("retrieval_degraded", False) or metrics.get("retrieval_degraded", False),
        fallback_reason=out.get("fallback_reason"),
        channel_health=channel_health,
        channels=channels if channels is not None else {},
        hierarchy_recall=hierarchy_recall,
        candidate_counts={
            "query_count": metrics.get("retrieval_query_count", 0),
            "citations": len(citations),
        },
        top_citations=[_trim_top_citation(citation) for citation in citations[: body.top_citations_limit]],
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
