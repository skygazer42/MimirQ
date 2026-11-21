"""Apply reranking and hierarchy expansion to retrieved evidence."""

import time
from typing import Any
from uuid import UUID

from langchain_core.documents import Document

from app.rag.retrieval.expansion.fetch import build_desired_pipeline_by_doc as _build_desired_pipeline_by_doc
from app.rag.retrieval.expansion.fetch import fetch_hierarchy_expansion_docs as _fetch_hierarchy_expansion_docs
from app.rag.retrieval.results import _log_orchestrator_fallback
from app.rag.retrieval.stages.post_rerank import _run_post_rerank_stage
from app.rag.retrieval.stages.state import RetrievalRuntimeState


def _run_hierarchy_expansion_stage(
    *,
    state: dict[str, Any],
    docs: list[Document],
    hierarchy_recall_enabled: bool,
    hierarchy_parent_depth: int,
    hierarchy_sibling_window: int,
    top_k: int,
) -> dict[str, Any]:
    result = {
        "docs": list(docs),
        "hierarchy_expand_attempted": False,
        "hierarchy_expand_used": False,
        "hierarchy_expand_error": None,
        "hierarchy_expand_elapsed": 0.0,
        "hierarchy_expand_meta": {"enabled": False, "reason": "not_run"},
    }
    if not (hierarchy_recall_enabled and docs and (hierarchy_parent_depth > 0 or hierarchy_sibling_window > 0)):
        return result

    result["hierarchy_expand_attempted"] = True
    exp_start = time.time()
    try:
        tenant_uuid: UUID | None = None
        try:
            tenant_id_raw = state.get("tenant_id")
            if tenant_id_raw is not None:
                tenant_uuid = UUID(str(tenant_id_raw))
        except (TypeError, ValueError):
            tenant_uuid = None

        from app.rag.retrieval.expansion.context import expand_hierarchy_documents  # noqa: WPS433

        desired_pipeline_by_doc = _build_desired_pipeline_by_doc(docs)
        max_added = max(
            0,
            int(top_k) * (int(hierarchy_parent_depth) + (2 * int(hierarchy_sibling_window))),
        )
        max_added = min(400, max_added or 120)
        expanded_docs, meta = expand_hierarchy_documents(
            docs,
            parent_depth=hierarchy_parent_depth,
            sibling_window=hierarchy_sibling_window,
            fetch_by_key=lambda pairs: _fetch_hierarchy_expansion_docs(
                pairs,
                tenant_uuid=tenant_uuid,
                desired_pipeline_by_doc=desired_pipeline_by_doc,
            ),
            max_added_docs=int(max_added),
        )
        result["hierarchy_expand_elapsed"] = max(0.0, float(time.time() - exp_start))
        result["hierarchy_expand_meta"] = dict(meta)
        if expanded_docs and meta["added_docs"] > 0:
            result["docs"] = expanded_docs
            result["hierarchy_expand_used"] = True
        return result
    except Exception as exc:  # noqa: BLE001
        _log_orchestrator_fallback("_run_hierarchy_expansion_stage", exc)
        result["hierarchy_expand_error"] = str(exc)[:200]
        result["hierarchy_expand_meta"] = {"enabled": False, "reason": "exception"}
        return result


def _run_retrieval_post_rerank_hierarchy_setup_phase(ctx: RetrievalRuntimeState) -> dict[str, Any] | None:
    post_rerank_result = _run_post_rerank_stage(
        state=ctx.state,
        docs=ctx.docs,
        query_for_retrieval=ctx.query_for_retrieval,
        top_k=ctx.top_k,
    )
    ctx.docs = list(post_rerank_result["docs"])
    ctx.post_rerank_enabled = bool(post_rerank_result["post_rerank_enabled"])
    ctx.post_rerank_used = bool(post_rerank_result["post_rerank_used"])
    ctx.post_rerank_provider = post_rerank_result["post_rerank_provider"]
    ctx.post_rerank_model_used = post_rerank_result["post_rerank_model_used"]
    ctx.post_rerank_elapsed = float(post_rerank_result["post_rerank_elapsed"])
    ctx.post_rerank_error = post_rerank_result["post_rerank_error"]
    ctx.post_rerank_candidates_n = int(post_rerank_result["post_rerank_candidates_n"])
    ctx.post_rerank_skip_reason = post_rerank_result["post_rerank_skip_reason"]
    ctx.post_rerank_cache_enabled = bool(post_rerank_result["post_rerank_cache_enabled"])
    ctx.post_rerank_cache_backend = post_rerank_result["post_rerank_cache_backend"]
    ctx.post_rerank_cache_hits = int(post_rerank_result["post_rerank_cache_hits"])
    ctx.post_rerank_cache_misses = int(post_rerank_result["post_rerank_cache_misses"])
    ctx.post_rerank_pipeline_enabled = bool(post_rerank_result["post_rerank_pipeline_enabled"])
    ctx.post_rerank_pipeline_used = bool(post_rerank_result["post_rerank_pipeline_used"])
    ctx.post_rerank_pipeline = list(post_rerank_result["post_rerank_pipeline"])
    ctx.post_rerank_pipeline_stages = list(post_rerank_result["post_rerank_pipeline_stages"])
    ctx.post_rerank_score_calibration_stats = dict(post_rerank_result["post_rerank_score_calibration_stats"])
    ctx.post_rerank_score_calibration_enabled = bool(ctx.post_rerank_score_calibration_stats["enabled"])
    ctx.post_rerank_score_calibration_alpha = float(ctx.post_rerank_score_calibration_stats["alpha"])
    ctx.post_rerank_score_calibration_used = bool(ctx.post_rerank_score_calibration_stats["used"])

    hierarchy_expand_result = _run_hierarchy_expansion_stage(
        state=ctx.state,
        docs=ctx.docs,
        hierarchy_recall_enabled=ctx.hierarchy_recall_enabled,
        hierarchy_parent_depth=ctx.hierarchy_parent_depth,
        hierarchy_sibling_window=ctx.hierarchy_sibling_window,
        top_k=ctx.top_k,
    )
    ctx.docs = list(hierarchy_expand_result["docs"])
    ctx.hierarchy_expand_attempted = bool(hierarchy_expand_result["hierarchy_expand_attempted"])
    ctx.hierarchy_expand_used = bool(hierarchy_expand_result["hierarchy_expand_used"])
    ctx.hierarchy_expand_error = hierarchy_expand_result["hierarchy_expand_error"]
    ctx.hierarchy_expand_elapsed = float(hierarchy_expand_result["hierarchy_expand_elapsed"])
    ctx.hierarchy_expand_meta = dict(hierarchy_expand_result["hierarchy_expand_meta"])
    ctx.retrieval_elapsed += float(ctx.hierarchy_expand_elapsed)

    ctx.hard_fallback_enabled = ctx.retrieval_contract_policy["hard_fallback_enabled"]
    ctx.hard_fallback_mode = ctx.retrieval_contract_policy["hard_fallback_mode"]
    ctx.hard_fallback_top_k = ctx.retrieval_contract_policy["hard_fallback_top_k"]
    ctx.hard_fallback_attempted = False
    ctx.hard_fallback_used = False
    ctx.hard_fallback_error: str | None = None
    ctx.hard_fallback_elapsed = 0.0
    ctx.hard_fallback_added_docs = 0
    ctx.hard_fallback_added_citations = 0
    ctx.hard_fallback_retriever_debug: dict[str, Any] | None = None
    ctx.contextual_followup_attempted = False
    ctx.contextual_followup_used = False
    ctx.contextual_followup_error: str | None = None
    ctx.contextual_followup_elapsed = 0.0
    ctx.contextual_followup_added_docs = 0
    ctx.contextual_followup_added_citations = 0
    ctx.contextual_followup_retriever_debug: dict[str, Any] | None = None
    ctx.contextual_followup_reason_codes: list[str] = []
    ctx.contextual_followup_selected_terms: list[str] = []
    ctx.contextual_followup_followup_query: str | None = None
    ctx.contextual_followup_query_hash: str | None = None
    ctx.iterative_pass_reason_codes: list[str] = []
    ctx.iterative_pass_hops: list[dict[str, Any]] = []
    ctx.iterative_pass_gap: dict[str, Any] | None = None
    return None
