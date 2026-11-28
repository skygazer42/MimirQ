"""Fuse query results and apply temporal and hierarchy policies."""

from typing import Any

from langchain_core.documents import Document

from app.infrastructure.config import settings
from app.rag.retrieval.ranking.hierarchy import _apply_hierarchy_tree_dedup
from app.rag.retrieval.ranking.queries import QueryCandidateGroup, QueryFusionSettings, fuse_query_candidates
from app.rag.retrieval.ranking.temporal import apply_recency_boost
from app.rag.retrieval.results import _log_orchestrator_fallback
from app.rag.retrieval.stages.state import RetrievalRuntimeState
from app.services.documents.freshness import fetch_document_updated_ts
from app.types.document_metadata import metadata_text


def _temporal_document_ids(docs: list[Document], *, limit: int) -> list[str]:
    document_ids: list[str] = []
    seen: set[str] = set()
    for doc in docs:
        document_id = metadata_text(doc.metadata, "document_id")
        if not document_id or document_id in seen:
            continue
        seen.add(document_id)
        document_ids.append(document_id)
        if limit and len(document_ids) >= limit:
            break
    return document_ids


def _apply_temporal_recency(ctx: RetrievalRuntimeState) -> None:
    if not ctx.temporal_intent_enabled or not ctx.docs:
        return
    boost_enabled = bool(settings.RAG_TEMPORAL_INTENT_RECENCY_BOOST_ENABLED)
    if not bool(ctx.temporal_intent_meta.get("detected")) or not boost_enabled:
        ctx.temporal_recency_meta = {"enabled": boost_enabled, "used": False, "reason": "not_detected"}
        return
    try:
        max_docs = max(0, int(settings.RAG_TEMPORAL_INTENT_MAX_DOCS))
        updated_ts = fetch_document_updated_ts(
            _temporal_document_ids(ctx.docs, limit=max_docs),
            tenant_id=ctx.state.get("tenant_id"),
            dataset_id=ctx.state.get("dataset_id"),
            max_docs=max_docs,
        )
        ctx.docs, ctx.temporal_recency_meta = apply_recency_boost(
            ctx.docs,
            updated_ts_by_document_id=updated_ts,
            boost_max=float(settings.RETRIEVAL_GOVERNANCE_LATEST_BOOST_MAX),
            window_days=int(settings.RETRIEVAL_GOVERNANCE_LATEST_WINDOW_DAYS),
        )
    except Exception as exc:  # noqa: BLE001
        _log_orchestrator_fallback("run_retrieval", exc)
        ctx.temporal_recency_meta = {"enabled": True, "used": False, "reason": f"exception:{str(exc)[:160]}"}


def _apply_hierarchy_tree_dedup_phase(ctx: RetrievalRuntimeState, refill_pool: list[Document]) -> None:
    if not (ctx.hierarchy_recall_enabled and ctx.hierarchy_tree_dedup and ctx.docs):
        return
    try:
        ctx.docs, ctx.tree_dedup_meta = _apply_hierarchy_tree_dedup(
            ctx.docs,
            refill=refill_pool,
            top_k=ctx.top_k,
            overfetch_factor=ctx.hierarchy_overfetch_factor,
        )
    except Exception as exc:
        _log_orchestrator_fallback("run_retrieval", exc)
        ctx.tree_dedup_meta = {"enabled": False, "reason": "exception"}


def _run_retrieval_fusion_phase(ctx: RetrievalRuntimeState) -> dict[str, Any] | None:
    ctx.top_k = ctx.retriever_update["k"]
    ctx.mq_diversify_enabled = bool(settings.MULTI_QUERY_DIVERSIFY_ENABLED) and bool(ctx.mq_enabled)
    mq_budget_raw = settings.MULTI_QUERY_DIVERSIFY_BUDGET
    ctx.mq_diversify_budget = max(0, min(mq_budget_raw, ctx.top_k))
    ctx.mq_diversify_used = False
    ctx.mq_diversify_selected_mq = 0
    ctx.mq_diversify_selected_non_mq = 0
    ctx.mq_diversify_fill_from_fused = 0
    ctx.family_aggregation_meta: dict[str, Any] = {"enabled": False, "reason": "not_run"}
    ctx.tree_dedup_meta: dict[str, Any] = {"enabled": False, "reason": "not_run"}
    fused = fuse_query_candidates(
        [
            QueryCandidateGroup(kind, docs)
            for kind, docs in zip(ctx.docs_by_query_kinds, ctx.docs_by_query, strict=False)
        ],
        settings=QueryFusionSettings(
            top_k=ctx.top_k,
            rrf_k=settings.RETRIEVAL_RRF_K,
            multi_query_enabled=ctx.mq_diversify_enabled,
            multi_query_budget=ctx.mq_diversify_budget,
            hierarchy=ctx.query_plan.routing.normalization.hierarchy,
        ),
    )
    ctx.docs = fused.documents
    ctx.family_aggregation_meta = fused.family_metadata
    ctx.mq_diversify_used = fused.diversity.used
    ctx.mq_diversify_selected_mq = fused.diversity.selected_mq
    ctx.mq_diversify_selected_non_mq = fused.diversity.selected_non_mq
    ctx.mq_diversify_fill_from_fused = fused.diversity.fill_from_fused
    docs_refill_pool = fused.refill_documents
    _apply_temporal_recency(ctx)
    _apply_hierarchy_tree_dedup_phase(ctx, docs_refill_pool)
    ctx.docs = ctx.docs[: max(0, ctx.top_k)]
    return None
