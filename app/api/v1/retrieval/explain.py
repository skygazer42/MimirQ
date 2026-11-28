"""
Single-query retrieval explain endpoint.

Returns a deterministic retrieval-only explain payload so contributors can
diagnose recall/rerank behavior without running the full chat flow.
"""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

import app.services.datasets.management as dataset_service
from app.api.dependencies import get_current_account_id, get_tenant_id
from app.api.schemas.conversations import RetrievalExplainRequest, RetrievalExplainResponse
from app.api.utils import DEFAULT_HTTP_EXCEPTION_RESPONSES as _DEFAULT_HTTP_EXCEPTION_RESPONSES
from app.infrastructure.database.connection import get_db
from app.rag.retrieval.orchestrator import run_retrieval
from app.rag.runtime.graph.state import build_rag_state
from app.services.retrieval.defaults import retrieval_options
from app.services.retrieval.scope import _resolve_retrieval_scope
from app.services.runtime.retrieval_limiter import (
    run_blocking_call_with_managed_session,
    run_blocking_retrieval_call_with_managed_session,
)

router = APIRouter(responses=_DEFAULT_HTTP_EXCEPTION_RESPONSES)


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
            **retrieval_options(rag_config),
            enable_query_decomposition=rag_config.enable_query_decomposition,
            enable_kg_query_expansion=rag_config.enable_kg_query_expansion,
            enable_kg_chunk_injection=rag_config.enable_kg_chunk_injection,
            kg_chunk_injection_max_chunks=rag_config.kg_chunk_injection_max_chunks,
            enable_kg_chunk_boost=rag_config.enable_kg_chunk_boost,
            kg_chunk_boost_weight=rag_config.kg_chunk_boost_weight,
            kg_chunk_boost_max_promoted=rag_config.kg_chunk_boost_max_promoted,
            metadata_filter=rag_config.metadata_filter,
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
