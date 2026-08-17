"""
Retrieval orchestration (evidence-first).

This module provides a *synchronous* retrieval runner that:
- rewrites/expands a query (optional, bounded)
- executes retrieval across one or more query variants
- fuses results and builds citation payloads
- computes abstain/guardrail signals
- emits a bounded, structured query_debug payload for downstream diagnostics

It is intentionally usable without the LangGraph orchestration layer.
"""

import asyncio
import concurrent.futures
import json
import time
from typing import Any
from uuid import UUID

from langchain_core.documents import Document

from app.core.config import settings
from app.core.utils import parse_csv
from app.query.normalize import normalize_query
from app.rag.core.citations import build_citations_from_docs
from app.rag.core.conversation import format_history_text
from app.rag.core.evidence_expectations import (
    evaluate_evidence_anchor_expectations,
)
from app.rag.core.hashing import stable_hash
from app.rag.core.logging import get_logger
from app.rag.core.query_rewrite_strategy import (
    build_query_rewrite_strategy_spec,
    get_query_rewrite_prompt_template,
)
from app.rag.core.temporal import (
    apply_recency_boost,
    detect_temporal_intent,
    fetch_document_updated_ts,
)
from app.rag.engine_support.doc_utils import DocUtilsMixin
from app.rag.industry_rules.runtime import apply_industry_rules_query_expansion
from app.rag.policy.must_recall import (
    MUST_RECALL_FAIL_REASON_TAXONOMY_V1,
    build_must_recall_fail_reasons,
    evaluate_required_source_keys,
)
from app.rag.policy.must_recall_auto import (
    infer_expected_source_keys,
    infer_required_anchor_fields,
)
from app.rag.policy.query_expansion import build_clause_fastlane_queries, build_lightweight_subquery_queries
from app.rag.policy.recall_obligation import build_must_recall_proof
from app.rag.query_expansion import generate_alias_queries
from app.rag.reranker.types import RerankCandidate
from app.rag.retrieval.contextual_followup import build_contextual_followup_query
from app.rag.retrieval.contract import resolve_retrieval_contract_policy
from app.rag.retrieval.evidence_gap import detect_evidence_gap
from app.rag.retrieval.orchestration.anchors import (
    _apply_metadata_exact_anchor_doc_ordering as _apply_metadata_exact_anchor_doc_ordering,
)
from app.rag.retrieval.orchestration.anchors import (
    _apply_metadata_exact_anchor_to_result as _apply_metadata_exact_anchor_to_result,
)
from app.rag.retrieval.orchestration.anchors import (
    _float_or_default as _float_or_default,
)
from app.rag.retrieval.orchestration.anchors import (
    _metadata_exact_anchor_doc_order_meta as _metadata_exact_anchor_doc_order_meta,
)
from app.rag.retrieval.orchestration.channel_budget import (
    _CHANNEL_BUDGET_POLICY_SCHEMA_V1 as _CHANNEL_BUDGET_POLICY_SCHEMA_V1,
)
from app.rag.retrieval.orchestration.channel_budget import (
    _channel_budget_policy_applied_meta as _channel_budget_policy_applied_meta,
)
from app.rag.retrieval.orchestration.channel_budget import (
    _channel_budget_policy_overrides as _channel_budget_policy_overrides,
)
from app.rag.retrieval.orchestration.channel_budget import (
    _channel_budget_policy_profiles as _channel_budget_policy_profiles,
)
from app.rag.retrieval.orchestration.channel_budget import (
    _channel_budget_policy_schema_meta as _channel_budget_policy_schema_meta,
)
from app.rag.retrieval.orchestration.channel_budget import (
    _channel_budget_policy_selected as _channel_budget_policy_selected,
)
from app.rag.retrieval.orchestration.channel_budget import (
    _coerce_channel_budgets as _coerce_channel_budgets,
)
from app.rag.retrieval.orchestration.channel_budget import (
    _coerce_channel_min_scores as _coerce_channel_min_scores,
)
from app.rag.retrieval.orchestration.channel_budget import (
    _safe_post_rerank_pipeline_item as _safe_post_rerank_pipeline_item,
)
from app.rag.retrieval.orchestration.channel_budget import (
    _safe_post_rerank_pipeline_summary as _safe_post_rerank_pipeline_summary,
)
from app.rag.retrieval.orchestration.channel_budget import (
    _select_channel_budget_profile as _select_channel_budget_profile,
)
from app.rag.retrieval.orchestration.channel_budget import (
    resolve_channel_budget_policy_overrides as resolve_channel_budget_policy_overrides,
)
from app.rag.retrieval.orchestration.citation_quality import (
    _build_empty_retrieval_diagnosis as _build_empty_retrieval_diagnosis,
)
from app.rag.retrieval.orchestration.citation_quality import (
    _build_parse_repair_actions_summary as _build_parse_repair_actions_summary,
)
from app.rag.retrieval.orchestration.citation_quality import (
    _citation_coverage_lists as _citation_coverage_lists,
)
from app.rag.retrieval.orchestration.citation_quality import (
    _classify_parse_risk as _classify_parse_risk,
)
from app.rag.retrieval.orchestration.citation_quality import (
    _count_parse_repair_actions as _count_parse_repair_actions,
)
from app.rag.retrieval.orchestration.citation_quality import (
    _coverage_proxy_from_citations as _coverage_proxy_from_citations,
)
from app.rag.retrieval.orchestration.citation_quality import (
    _diagnose_empty_retrieval as _diagnose_empty_retrieval,
)
from app.rag.retrieval.orchestration.citation_quality import (
    _empty_retrieval_reason_counts as _empty_retrieval_reason_counts,
)
from app.rag.retrieval.orchestration.citation_quality import (
    _extract_parse_quality_score as _extract_parse_quality_score,
)
from app.rag.retrieval.orchestration.citation_quality import (
    _main_retrieval_per_query_item as _main_retrieval_per_query_item,
)
from app.rag.retrieval.orchestration.citation_quality import (
    _normalize_parse_repair_payload as _normalize_parse_repair_payload,
)
from app.rag.retrieval.orchestration.citation_quality import (
    _parse_quality_low_sample as _parse_quality_low_sample,
)
from app.rag.retrieval.orchestration.citation_quality import (
    _parse_quality_recommendation as _parse_quality_recommendation,
)
from app.rag.retrieval.orchestration.citation_quality import (
    _parse_quality_risk_counters as _parse_quality_risk_counters,
)
from app.rag.retrieval.orchestration.citation_quality import (
    _parse_repair_gate_passed as _parse_repair_gate_passed,
)
from app.rag.retrieval.orchestration.citation_quality import (
    _parse_repair_run_id as _parse_repair_run_id,
)
from app.rag.retrieval.orchestration.citation_quality import (
    _parse_risk_hardcase_eligible as _parse_risk_hardcase_eligible,
)
from app.rag.retrieval.orchestration.citation_quality import (
    _parse_risk_level as _parse_risk_level,
)
from app.rag.retrieval.orchestration.citation_quality import (
    _retriever_enrichment_debug as _retriever_enrichment_debug,
)
from app.rag.retrieval.orchestration.citation_quality import (
    _sanitize_parse_repair_actions as _sanitize_parse_repair_actions,
)
from app.rag.retrieval.orchestration.citation_quality import (
    _summarize_parse_quality_risk as _summarize_parse_quality_risk,
)
from app.rag.retrieval.orchestration.citation_quality import (
    _top_doc_share as _top_doc_share,
)
from app.rag.retrieval.orchestration.common import (
    _coerce_optional_bool as _coerce_optional_bool,
)
from app.rag.retrieval.orchestration.common import (
    _coerce_optional_float as _coerce_optional_float,
)
from app.rag.retrieval.orchestration.common import (
    _coerce_optional_int as _coerce_optional_int,
)
from app.rag.retrieval.orchestration.common import (
    _doc_key as _doc_key,
)
from app.rag.retrieval.orchestration.common import (
    _log_orchestrator_fallback as _log_orchestrator_fallback,
)
from app.rag.retrieval.orchestration.common import (
    _safe_float as _safe_float,
)
from app.rag.retrieval.orchestration.common import (
    _safe_int as _safe_int,
)
from app.rag.retrieval.orchestration.corpus_cache_tokens import resolve_corpus_cache_token
from app.rag.retrieval.orchestration.debug_sanitize import (
    _bounded_string_sample as _bounded_string_sample,
)
from app.rag.retrieval.orchestration.debug_sanitize import (
    _copy_present_debug_keys as _copy_present_debug_keys,
)
from app.rag.retrieval.orchestration.debug_sanitize import (
    _sanitize_counts_debug as _sanitize_counts_debug,
)
from app.rag.retrieval.orchestration.debug_sanitize import (
    _sanitize_diversity_debug as _sanitize_diversity_debug,
)
from app.rag.retrieval.orchestration.debug_sanitize import (
    _sanitize_enrich_pass_debug as _sanitize_enrich_pass_debug,
)
from app.rag.retrieval.orchestration.debug_sanitize import (
    _sanitize_governance_policy_debug as _sanitize_governance_policy_debug,
)
from app.rag.retrieval.orchestration.debug_sanitize import (
    _sanitize_metadata_filter_debug as _sanitize_metadata_filter_debug,
)
from app.rag.retrieval.orchestration.debug_sanitize import (
    _sanitize_metadata_filter_ops as _sanitize_metadata_filter_ops,
)
from app.rag.retrieval.orchestration.debug_sanitize import (
    _sanitize_query_normalization_debug as _sanitize_query_normalization_debug,
)
from app.rag.retrieval.orchestration.debug_sanitize import (
    _sanitize_retriever_debug as _sanitize_retriever_debug,
)
from app.rag.retrieval.orchestration.debug_sanitize import (
    _sanitize_timing_debug as _sanitize_timing_debug,
)
from app.rag.retrieval.orchestration.finalize_trace import (
    RetrievalTraceStageInput,
    build_retrieval_trace_stage,
)
from app.rag.retrieval.orchestration.hierarchy import (
    _apply_hierarchy_family_aggregation as _apply_hierarchy_family_aggregation,
)
from app.rag.retrieval.orchestration.hierarchy import (
    _apply_hierarchy_tree_dedup as _apply_hierarchy_tree_dedup,
)
from app.rag.retrieval.orchestration.hierarchy import (
    _build_hierarchy_family_feature_payload as _build_hierarchy_family_feature_payload,
)
from app.rag.retrieval.orchestration.hierarchy import (
    _build_hierarchy_family_features as _build_hierarchy_family_features,
)
from app.rag.retrieval.orchestration.hierarchy import (
    _doc_base_score as _doc_base_score,
)
from app.rag.retrieval.orchestration.hierarchy import (
    _doc_stable_debug_id as _doc_stable_debug_id,
)
from app.rag.retrieval.orchestration.hierarchy import (
    _family_aggregation_meta as _family_aggregation_meta,
)
from app.rag.retrieval.orchestration.hierarchy import (
    _family_aggregation_sort_key as _family_aggregation_sort_key,
)
from app.rag.retrieval.orchestration.hierarchy import (
    _hierarchy_dedup_candidates as _hierarchy_dedup_candidates,
)
from app.rag.retrieval.orchestration.hierarchy import (
    _hierarchy_dedup_limits as _hierarchy_dedup_limits,
)
from app.rag.retrieval.orchestration.hierarchy import (
    _hierarchy_dedup_meta as _hierarchy_dedup_meta,
)
from app.rag.retrieval.orchestration.hierarchy import (
    _hierarchy_dedup_output as _hierarchy_dedup_output,
)
from app.rag.retrieval.orchestration.hierarchy import (
    _hierarchy_node_parent_keys as _hierarchy_node_parent_keys,
)
from app.rag.retrieval.orchestration.hierarchy import (
    _HierarchyDedupState as _HierarchyDedupState,
)
from app.rag.retrieval.orchestration.hierarchy import (
    _keep_hierarchy_dedup_doc as _keep_hierarchy_dedup_doc,
)
from app.rag.retrieval.orchestration.hierarchy import (
    _new_hierarchy_dedup_state as _new_hierarchy_dedup_state,
)
from app.rag.retrieval.orchestration.hierarchy import (
    _rank_hierarchy_family_docs as _rank_hierarchy_family_docs,
)
from app.rag.retrieval.orchestration.hierarchy import (
    _remove_hierarchy_dedup_doc as _remove_hierarchy_dedup_doc,
)
from app.rag.retrieval.orchestration.hierarchy import (
    _resolve_family_aggregation_strategy as _resolve_family_aggregation_strategy,
)
from app.rag.retrieval.orchestration.hierarchy import (
    _resolve_hierarchy_family_collapse_key as _resolve_hierarchy_family_collapse_key,
)
from app.rag.retrieval.orchestration.hierarchy import (
    _resolve_hierarchy_node_key as _resolve_hierarchy_node_key,
)
from app.rag.retrieval.orchestration.hierarchy import (
    _resolve_hierarchy_parent_key as _resolve_hierarchy_parent_key,
)
from app.rag.retrieval.orchestration.hierarchy import (
    _scan_hierarchy_dedup_candidates as _scan_hierarchy_dedup_candidates,
)
from app.rag.retrieval.orchestration.hierarchy import (
    _update_hierarchy_family_feature as _update_hierarchy_family_feature,
)
from app.rag.retrieval.orchestration.intent_router import (
    build_router_layers as build_router_layers,
)
from app.rag.retrieval.orchestration.intent_router import (
    route_adaptive_retrieval_overrides as route_adaptive_retrieval_overrides,
)
from app.rag.retrieval.orchestration.intent_router import (
    route_intent as route_intent,
)
from app.rag.retrieval.orchestration.intent_router import (
    route_retrieval_preset as route_retrieval_preset,
)
from app.rag.retrieval.orchestration.kg_merge_boost import (
    _apply_kg_chunk_boost as _apply_kg_chunk_boost,
)
from app.rag.retrieval.orchestration.kg_merge_boost import (
    _coerce_uuid_list as _coerce_uuid_list,
)
from app.rag.retrieval.orchestration.kg_merge_boost import (
    _fetch_document_chunks_for_kg_injection as _fetch_document_chunks_for_kg_injection,
)
from app.rag.retrieval.orchestration.kg_merge_boost import (
    _kg_boost_document as _kg_boost_document,
)
from app.rag.retrieval.orchestration.kg_merge_boost import (
    _kg_boost_output as _kg_boost_output,
)
from app.rag.retrieval.orchestration.kg_merge_boost import (
    _kg_boost_promoted_indexes as _kg_boost_promoted_indexes,
)
from app.rag.retrieval.orchestration.kg_merge_boost import (
    _kg_boost_ranked_rows as _kg_boost_ranked_rows,
)
from app.rag.retrieval.orchestration.kg_merge_boost import (
    _kg_boost_row as _kg_boost_row,
)
from app.rag.retrieval.orchestration.kg_merge_boost import (
    _kg_boost_rows as _kg_boost_rows,
)
from app.rag.retrieval.orchestration.kg_merge_boost import (
    _kg_chunk_boost_disabled_reason as _kg_chunk_boost_disabled_reason,
)
from app.rag.retrieval.orchestration.kg_merge_boost import (
    _kg_chunk_boost_meta as _kg_chunk_boost_meta,
)
from app.rag.retrieval.orchestration.kg_merge_boost import (
    _kg_signal_score as _kg_signal_score,
)
from app.rag.retrieval.orchestration.kg_merge_boost import (
    _merge_kg_docs_preserving_main as _merge_kg_docs_preserving_main,
)
from app.rag.retrieval.orchestration.kg_merge_boost import (
    _merge_kg_metadata_into_main as _merge_kg_metadata_into_main,
)
from app.rag.retrieval.orchestration.kg_merge_boost import (
    _resolve_kg_scope as _resolve_kg_scope,
)
from app.rag.retrieval.orchestration.out_of_scope_live_gate import (
    maybe_apply_out_of_scope_live_guard as maybe_apply_out_of_scope_live_guard,
)
from app.rag.retrieval.orchestration.out_of_scope_live_gate import (
    run_default_out_of_scope_live_guard as run_default_out_of_scope_live_guard,
)
from app.rag.retrieval.orchestration.query_contract import (
    RetrievalConfigSnapshotInput,
    build_retrieval_config_snapshot,
)
from app.rag.retrieval.orchestration.query_invocation import (
    QueryInvocationRecordInput,
    build_query_invocation_record,
)
from app.rag.retrieval.orchestration.query_variants import (
    QueryVariantStageInput,
    build_query_variant_stage,
)
from app.rag.retrieval.orchestration.rerank_result_cache import (
    build_evidence_post_rerank_cache_key,
    fingerprint_rerank_candidates,
    get_cached_evidence_post_rerank_result,
    get_evidence_post_rerank_cache_backend,
    set_cached_evidence_post_rerank_result,
)
from app.rag.retrieval.orchestration.reranker_factory import (
    describe_reranker_provider as describe_reranker_provider,
)
from app.rag.retrieval.orchestration.reranker_factory import (
    get_reranker as get_reranker,
)
from app.rag.retrieval.orchestration.retriever_shim import (
    hybrid_retriever as hybrid_retriever,
)
from app.rag.retrieval.orchestration.text_helpers import (
    build_abstain_followup as build_abstain_followup,
)
from app.rag.retrieval.orchestration.text_helpers import (
    normalize_retrieval_mode as normalize_retrieval_mode,
)
from app.rag.retrieval.orchestration.text_helpers import (
    parse_json_from_text as parse_json_from_text,
)
from app.rag.retrieval.orchestration.text_helpers import (
    should_rewrite_query as should_rewrite_query,
)
from app.rag.retrieval.orchestrator_support_contracts import (
    apply_routing_phase as _apply_routing_phase_impl,
)
from app.rag.retrieval.orchestrator_support_contracts import (
    resolve_contract_phase as _resolve_contract_phase_impl,
)
from app.rag.retrieval.orchestrator_support_hierarchy import (
    build_desired_pipeline_by_doc as _build_desired_pipeline_by_doc_impl,
)
from app.rag.retrieval.orchestrator_support_hierarchy import (
    chunk_document_from_row as _chunk_document_from_row_impl,
)
from app.rag.retrieval.orchestrator_support_hierarchy import (
    fetch_hierarchy_expansion_docs as _fetch_hierarchy_expansion_docs_impl,
)
from app.rag.retrieval.orchestrator_support_hierarchy import (
    hierarchy_fetch_pairs_by_doc as _hierarchy_fetch_pairs_by_doc_impl,
)
from app.rag.retrieval.orchestrator_support_hierarchy import (
    safe_kg_path_provenance as _safe_kg_path_provenance_impl,
)
from app.rag.retrieval.orchestrator_support_post_rerank import (
    build_reranked_prefix as _build_reranked_prefix_impl,
)
from app.rag.retrieval.orchestrator_support_post_rerank import (
    post_rerank_settings as _post_rerank_settings_impl,
)
from app.rag.retrieval.orchestrator_support_post_rerank import (
    run_post_rerank_pipeline_mode as _run_post_rerank_pipeline_mode_impl,
)
from app.rag.retrieval.orchestrator_support_post_rerank import (
    run_post_rerank_single_mode as _run_post_rerank_single_mode_impl,
)
from app.rag.retrieval.orchestrator_support_post_rerank import (
    run_post_rerank_stage as _run_post_rerank_stage_impl,
)
from app.rag.retrieval.orchestrator_support_runtime import (
    RetrievalRuntimeState,
    run_retrieval_runtime,
)
from app.services.hardcase_discovery_service import (
    build_parse_risk_hardcase_candidate,
    evaluate_parse_risk_auto_enqueue_policy,
)
from app.services.router_prometheus_metrics import observe_router_layers

logger = get_logger(__name__)
_RETRIEVAL_ORCHESTRATOR_FALLBACK_LOG_MESSAGE = "Ignoring non-critical retrieval orchestrator fallback failure: %s"


def get_rag_engine():  # noqa: ANN201
    """
    Indirection for tests/monkeypatching while keeping module imports lightweight.

    (Many unit tests patch `app.rag.retrieval.orchestrator.get_rag_engine`.)
    """

    from app.rag.engine import get_rag_engine as _get_rag_engine

    return _get_rag_engine()


def _get_langchain_text_pipeline_primitives() -> tuple[Any, Any]:
    from langchain_core.output_parsers import StrOutputParser
    from langchain_core.prompts import ChatPromptTemplate

    return ChatPromptTemplate, StrOutputParser


def _get_kg_search() -> Any:
    from app.rag.kg.pipeline import kg_search

    return kg_search


async def kg_search(  # noqa: ANN201
    *,
    query: str,
    tenant_id: UUID | None = None,
    document_ids: list[UUID] | None = None,
    dataset_id: UUID | None = None,
    dataset_ids: list[UUID] | None = None,
    account_id: str | None = None,
) -> dict[str, Any]:
    """
    Thin wrapper around the KG pipeline search, kept as a module attribute so tests
    can monkeypatch it without importing the KG module.
    """

    fn = _get_kg_search()
    result = await fn(
        query=query,
        tenant_id=tenant_id,
        document_ids=document_ids,
        dataset_id=dataset_id,
        dataset_ids=dataset_ids,
        account_id=account_id,
    )
    return result if isinstance(result, dict) else {}


def _build_history_text(history: list[dict[str, str]] | None) -> str:
    """Compress history to readable text, keep only within window."""
    return format_history_text(history, window=settings.CHAT_HISTORY_WINDOW)


def _query_decomposition_settings(enabled: bool | None) -> tuple[bool, int, int, int, bool, str]:
    dq_n = max(0, min(_safe_int(settings.QUERY_DECOMPOSITION_MAX_SUBQUESTIONS), 8))
    dq_min_chars = max(0, _safe_int(settings.QUERY_DECOMPOSITION_MIN_CHARS))
    dq_max_chars = max(0, _safe_int(settings.QUERY_DECOMPOSITION_MAX_CHARS))
    dq_enabled = bool(settings.ENABLE_QUERY_DECOMPOSITION) if enabled is None else bool(enabled)
    heuristic_enabled = bool(getattr(settings, "QUERY_DECOMPOSITION_HEURISTIC_FALLBACK_ENABLED", True))
    llm_api_key = str(getattr(settings, "LLM_API_KEY", "") or "").strip()
    return dq_enabled, dq_n, dq_min_chars, dq_max_chars, heuristic_enabled, llm_api_key


def _query_decomposition_allowed(
    query: str, *, enabled: bool, max_questions: int, min_chars: int, max_chars: int
) -> bool:
    return bool(
        enabled and max_questions > 0 and len(query) >= min_chars and (max_chars <= 0 or len(query) <= max_chars)
    )


def _heuristic_decompose(query: str, *, max_questions: int) -> tuple[list[str], dict[str, Any]]:
    from app.rag.core.text import heuristic_decompose_query

    sub_questions = heuristic_decompose_query(query, max_subquestions=max_questions)
    meta = (
        {"ok": True, "method": "heuristic", "error": None}
        if sub_questions
        else {"ok": False, "method": None, "error": None}
    )
    return sub_questions, meta


def _normalized_decomposed_question(item: Any, *, original_query: str, seen: set[str]) -> str:
    if not isinstance(item, str):
        return ""
    question = (item or "").strip().strip('"').strip()
    if not question or question == original_query or question in seen:
        return ""
    if len(question) > 500:
        return question[:500] + "..."
    return question


def _normalize_decomposed_questions(raw: Any, *, original_query: str, max_questions: int) -> list[str]:
    if not isinstance(raw, list):
        return []
    seen: set[str] = set()
    out: list[str] = []
    for item in raw:
        question = _normalized_decomposed_question(item, original_query=original_query, seen=seen)
        if not question:
            continue
        seen.add(question)
        out.append(question)
        if len(out) >= max_questions:
            break
    return out


def _invoke_decomposition_chain(
    query_for_retrieval: str,
    engine: Any,
    *,
    max_questions: int,
) -> tuple[list[str], float, str | None, dict[str, Any]]:
    dq_llm = engine.models.get("fast") or engine.models.get("default")  # type: ignore[attr-defined]
    model_used = getattr(dq_llm, "model_name", None) or getattr(dq_llm, "model", None)
    try:
        _, str_output_parser_cls = _get_langchain_text_pipeline_primitives()
        dq_chain = (
            engine.decompose_prompt  # type: ignore[attr-defined]
            | dq_llm.bind(temperature=settings.QUERY_DECOMPOSITION_TEMPERATURE)
            | str_output_parser_cls()
        )
        started_at = time.time()
        raw = dq_chain.invoke({"query": query_for_retrieval, "n": max_questions})
        elapsed = time.time() - started_at
        data, parse_meta = parse_json_from_text(raw, expected="array")
        questions = _normalize_decomposed_questions(
            data,
            original_query=query_for_retrieval,
            max_questions=max_questions,
        )
        return questions, elapsed, model_used, parse_meta
    except Exception as exc:  # noqa: BLE001
        _log_orchestrator_fallback("_decompose_query", exc)
        return [], 0.0, model_used, {"ok": False, "method": None, "error": str(exc)[:200]}


def _decompose_query(
    query_for_retrieval: str,
    engine: Any | None,
    *,
    enabled: bool | None = None,
) -> tuple[list[str], float, str | None, dict[str, Any]]:
    dq_enabled, dq_n, dq_min_chars, dq_max_chars, heuristic_enabled, llm_api_key = _query_decomposition_settings(
        enabled
    )
    parse_meta: dict[str, Any] = {"ok": False, "method": None, "error": None}
    if not _query_decomposition_allowed(
        query_for_retrieval, enabled=dq_enabled, max_questions=dq_n, min_chars=dq_min_chars, max_chars=dq_max_chars
    ):
        return [], 0.0, None, parse_meta

    if heuristic_enabled and not llm_api_key:
        sub_questions, parse_meta = _heuristic_decompose(query_for_retrieval, max_questions=dq_n)
        return sub_questions, 0.0, None, parse_meta

    if engine is None:
        engine = get_rag_engine()

    sub_questions, elapsed, model_used, parse_meta = _invoke_decomposition_chain(
        query_for_retrieval,
        engine,
        max_questions=dq_n,
    )
    if heuristic_enabled and not sub_questions and not bool(parse_meta.get("ok")):
        sub_questions, heuristic_meta = _heuristic_decompose(query_for_retrieval, max_questions=dq_n)
        if sub_questions:
            return sub_questions, 0.0, None, heuristic_meta

    return sub_questions, elapsed, model_used, parse_meta


def _resolve_post_rerank_corpus_cache_token(state: dict[str, Any]) -> str | None:
    db = state.get("db")
    tenant_id = state.get("tenant_id")
    if db is None or tenant_id is None:
        return None
    try:
        tenant_uuid = UUID(str(tenant_id))
    except (TypeError, ValueError, AttributeError):
        return None

    dataset_id_raw = state.get("dataset_id")
    dataset_uuid: UUID | None = None
    if dataset_id_raw is not None:
        try:
            dataset_uuid = UUID(str(dataset_id_raw))
        except (TypeError, ValueError, AttributeError):
            dataset_uuid = None

    document_ids_raw = state.get("document_ids") or []
    document_ids: list[UUID] = []
    for raw in document_ids_raw:
        try:
            document_ids.append(UUID(str(raw)))
        except (TypeError, ValueError, AttributeError):
            continue

    try:
        return resolve_corpus_cache_token(
            db,
            tenant_id=tenant_uuid,
            dataset_id=dataset_uuid,
            document_ids=document_ids,
        )
    except Exception as exc:
        _log_orchestrator_fallback("_resolve_post_rerank_corpus_cache_token", exc)
        return None


def _build_no_retrieval_response(
    state: dict[str, Any],
    *,
    question: str,
    no_retrieval_intent: dict[str, Any],
) -> dict[str, Any]:
    requested_retrieval_mode = state.get("retrieval_mode", "hybrid") or "hybrid"
    requested_retrieval_profile = state.get("retrieval_profile")
    retrieval_mode = normalize_retrieval_mode(requested_retrieval_mode)
    profile_norm = str(requested_retrieval_profile or "").strip().lower() or None
    metrics = dict(state.get("metrics") or {})
    metrics["retrieval_elapsed_sec"] = 0.0
    metrics["retrieval_mode"] = retrieval_mode
    metrics["retrieval_mode_requested"] = requested_retrieval_mode
    metrics["retrieval_mode_auto_routed"] = False
    metrics["retrieval_profile"] = profile_norm
    metrics["retrieval_profile_requested"] = profile_norm
    metrics["retrieval_bypassed"] = True
    metrics["retrieval_bypass_reason"] = "no_retrieval_intent"
    metrics["retrieval_bypass_intent"] = no_retrieval_intent.get("intent")
    metrics["intent_router_enabled"] = False
    metrics["intent_router_used"] = False

    query_debug: dict[str, Any] = {
        "original": question,
        "normalized": question,
        "applied_rules": [],
        "expansions": [],
        "contributions": [],
        "channels": None,
        "query_for_retrieval": question,
        "rewrite_used": False,
        "retrieval_profile": profile_norm,
        "retrieval_profile_requested": profile_norm,
        "no_retrieval_intent": dict(no_retrieval_intent),
    }
    router_layers = build_router_layers(query=question, intent_meta=dict(no_retrieval_intent))
    query_debug["router_layers"] = router_layers
    observe_router_layers(router_layers)
    retrieval_trace: dict[str, Any] = {
        "schema": "mimirq.retrieval_trace_pass.v1",
        "query_for_retrieval_hash": stable_hash(question),
        "requested_retrieval_mode": str(requested_retrieval_mode or ""),
        "retrieval_mode": str(retrieval_mode or ""),
        "retrieval_mode_auto_routed": False,
        "retrieval_profile": profile_norm,
        "retrieval_profile_requested": profile_norm,
        "intent_router": {"enabled": False, "used": False},
        "adaptive_router": {"enabled": False, "used": False},
        "channel_budget_policy": {"enabled": False, "used": False},
        "router_layers": router_layers,
        "no_retrieval_intent": dict(no_retrieval_intent),
    }
    return {
        **state,
        "query_for_retrieval": question,
        "docs": [],
        "citations": [],
        "metrics": metrics,
        "abstain_triggered": False,
        "abstain_reason": None,
        "query_debug": query_debug,
        "retrieval_trace": retrieval_trace,
    }


def _post_rerank_minmax(values: list[float]) -> list[float]:
    if not values:
        return []
    lo = min(values)
    hi = max(values)
    rng = hi - lo
    if rng <= 0.0:
        return [0.0 for _ in values]
    return [(float(value) - float(lo)) / float(rng) for value in values]


def _post_rerank_row(idx: int, doc: Document) -> dict[str, Any]:
    meta = dict(doc.metadata or {})
    rid = _doc_key(doc) or str(idx)
    base_raw = meta.get("retrieval_score")
    if base_raw is None:
        base_raw = meta.get("score", 0.0)
    try:
        retrieval_score = float(base_raw or 0.0)
    except (TypeError, ValueError, AttributeError):
        retrieval_score = 0.0

    rerank_raw = meta.get("rerank_score")
    try:
        rerank_score = float(rerank_raw) if rerank_raw is not None else None
    except (TypeError, ValueError, AttributeError):
        rerank_score = None

    return {
        "idx": int(idx),
        "rid": rid,
        "doc": doc,
        "meta": meta,
        "retrieval_score": float(retrieval_score),
        "rerank_score": rerank_score,
    }


def _calibrated_post_rerank_rows(
    rows: list[dict[str, Any]],
    *,
    alpha: float,
) -> list[dict[str, Any]]:
    ranked_rows = [row for row in rows if row.get("rerank_score") is not None]
    retrieval_norm = _post_rerank_minmax([float(row.get("retrieval_score") or 0.0) for row in rows])
    rerank_norm_values = _post_rerank_minmax([float(row.get("rerank_score") or 0.0) for row in ranked_rows])
    rerank_norm_by_id = {
        str(ranked_rows[index].get("rid") or ""): float(rerank_norm_values[index])
        for index in range(min(len(ranked_rows), len(rerank_norm_values)))
    }

    for index, row in enumerate(rows):
        base_norm = float(retrieval_norm[index]) if index < len(retrieval_norm) else 0.0
        rerank_norm = rerank_norm_by_id.get(str(row.get("rid") or ""))
        calibrated = base_norm
        if rerank_norm is not None:
            calibrated = (alpha * float(rerank_norm)) + ((1.0 - alpha) * float(base_norm))
        row["retrieval_score_norm"] = float(base_norm)
        row["rerank_score_norm"] = float(rerank_norm) if rerank_norm is not None else None
        row["calibrated_score"] = float(calibrated)

    return sorted(
        rows,
        key=lambda row: (
            -float(row.get("calibrated_score") or 0.0),
            -float(row.get("rerank_score_norm") or -1.0),
            -float(row.get("retrieval_score_norm") or 0.0),
            int(row.get("idx") or 0),
        ),
    )


def _calibrate_post_rerank_prefix(
    prefix_docs: list[Document],
    *,
    enabled: bool,
    alpha: float,
    stats: dict[str, Any],
) -> tuple[list[Document], bool]:
    if not enabled:
        return prefix_docs, False
    if not prefix_docs:
        stats["skip_reason"] = "no_candidates"
        return prefix_docs, False

    rows = [_post_rerank_row(index, doc) for index, doc in enumerate(prefix_docs)]
    ranked_rows = [row for row in rows if row.get("rerank_score") is not None]
    if len(ranked_rows) < 2:
        stats["skip_reason"] = "insufficient_rerank_scores"
        stats["eligible_docs"] = int(len(ranked_rows))
        return prefix_docs, False

    rows_sorted = _calibrated_post_rerank_rows(rows, alpha=alpha)
    moved = sum(1 for index, row in enumerate(rows_sorted) if int(row.get("idx") or 0) != index)
    top_changed = bool(rows_sorted) and int(rows_sorted[0].get("idx") or 0) != 0

    out_docs: list[Document] = []
    for row in rows_sorted:
        meta = dict(row.get("meta") or {})
        calibrated = float(row.get("calibrated_score") or 0.0)
        meta["rerank_score_calibrated"] = round(calibrated, 6)
        meta["score"] = float(calibrated)
        doc = row.get("doc")
        if isinstance(doc, Document):
            out_docs.append(
                Document(
                    page_content=doc.page_content,
                    metadata=meta,
                    id=getattr(doc, "id", None) or meta.get("chunk_id"),
                )
            )

    stats.update(
        {
            "used": True,
            "applied_docs": int(len(rows)),
            "eligible_docs": int(len(ranked_rows)),
            "moved_positions": int(moved),
            "top_changed": bool(top_changed),
        }
    )
    return out_docs, True


def _calibrate_post_rerank_prefix_docs(
    prefix_docs: list[Document],
    *,
    enabled: bool,
    alpha: float,
    stats: dict[str, Any],
) -> tuple[list[Document], bool]:
    """Compatibility hook for callers that patch post-rerank calibration."""
    return _calibrate_post_rerank_prefix(
        prefix_docs,
        enabled=enabled,
        alpha=alpha,
        stats=stats,
    )


def _build_post_rerank_candidates(
    docs: list[Document],
    *,
    limit: int,
) -> tuple[list[RerankCandidate], dict[str, Document]]:
    candidates: list[RerankCandidate] = []
    id_to_doc: dict[str, Document] = {}
    for doc in docs[:limit]:
        rid = _doc_key(doc)
        text = (doc.page_content or "").strip()
        if not rid or not text:
            continue
        meta = dict(doc.metadata or {})
        candidates.append(RerankCandidate(id=rid, text=text, metadata=meta))
        id_to_doc[rid] = doc
    return candidates, id_to_doc


def _get_cached_post_rerank_result(
    *,
    state: dict[str, Any],
    provider: str,
    top_n: int,
    query_for_retrieval: str,
    candidates: list[RerankCandidate],
    cache_enabled: bool,
    corpus_cache_token: str | None,
) -> tuple[Any, str | None, bool, int, int]:
    if not cache_enabled:
        return None, None, False, 0, 0
    try:
        cand_fp = fingerprint_rerank_candidates(candidates)
        cache_key = build_evidence_post_rerank_cache_key(
            tenant_id=state.get("tenant_id"),
            account_id=state.get("account_id"),
            provider=provider,
            top_n=top_n,
            query=query_for_retrieval,
            candidates_fingerprint=cand_fp,
            corpus_cache_token=corpus_cache_token,
        )
        cached = get_cached_evidence_post_rerank_result(cache_key)
        if cached is not None:
            return cached, cache_key, True, 1, 0
        return None, cache_key, False, 0, 1
    except Exception as exc:
        _log_orchestrator_fallback("_get_cached_post_rerank_result", exc)
        return None, None, False, 0, 0


def _execute_post_rerank(
    *,
    state: dict[str, Any],
    provider: str,
    top_n: int,
    query_for_retrieval: str,
    candidates: list[RerankCandidate],
    cache_enabled: bool,
    cache_key: str | None,
    cached_result: Any,
) -> tuple[Any, float]:
    if cached_result is not None:
        return cached_result, 0.0
    reranker = get_reranker(provider)
    rerank_start = time.time()
    rerank_result = reranker.rerank(
        query=query_for_retrieval,
        candidates=candidates,
        top_n=top_n,
        tenant_id=str(state.get("tenant_id") or "").strip() or None,
        query_type=str(state.get("query_type") or "").strip() or None,
    )
    if cache_enabled and cache_key:
        try:
            set_cached_evidence_post_rerank_result(cache_key, rerank_result)
        except Exception as exc:
            logger.debug(_RETRIEVAL_ORCHESTRATOR_FALLBACK_LOG_MESSAGE, exc)
    return rerank_result, float(rerank_result.elapsed_sec or (time.time() - rerank_start))


def _build_reranked_prefix(
    *,
    docs_prefix: list[Document],
    id_to_doc: dict[str, Document],
    rerank_result: Any,
    provider: str,
    elapsed_sec: float,
    model_used: str | None,
    annotate_scores: bool,
) -> list[Document]:
    return _build_reranked_prefix_impl(
        docs_prefix=docs_prefix,
        id_to_doc=id_to_doc,
        rerank_result=rerank_result,
        provider=provider,
        elapsed_sec=elapsed_sec,
        model_used=model_used,
        annotate_scores=annotate_scores,
        doc_key_fn=_doc_key,
    )


def _post_rerank_settings(state: dict[str, Any]) -> dict[str, Any]:
    return _post_rerank_settings_impl(
        state,
        cache_backend_fn=get_evidence_post_rerank_cache_backend,
        corpus_cache_token_fn=_resolve_post_rerank_corpus_cache_token,
    )


def _run_post_rerank_single_mode(
    *,
    state: dict[str, Any],
    docs: list[Document],
    query_for_retrieval: str,
    top_k: int,
    provider: str,
    top_n: int,
    cache_enabled: bool,
    corpus_cache_token: str | None,
    score_calibration_enabled: bool,
    score_calibration_alpha: float,
    score_calibration_stats: dict[str, Any],
) -> dict[str, Any]:
    return _run_post_rerank_single_mode_impl(
        state=state,
        docs=docs,
        query_for_retrieval=query_for_retrieval,
        top_k=top_k,
        provider=provider,
        top_n=top_n,
        cache_enabled=cache_enabled,
        corpus_cache_token=corpus_cache_token,
        score_calibration_enabled=score_calibration_enabled,
        score_calibration_alpha=score_calibration_alpha,
        score_calibration_stats=score_calibration_stats,
        build_candidates_fn=_build_post_rerank_candidates,
        get_cached_result_fn=_get_cached_post_rerank_result,
        execute_post_rerank_fn=_execute_post_rerank,
        build_reranked_prefix_fn=_build_reranked_prefix,
        calibrate_prefix_fn=_calibrate_post_rerank_prefix_docs,
    )


def _run_post_rerank_pipeline_mode(
    *,
    state: dict[str, Any],
    docs: list[Document],
    query_for_retrieval: str,
    top_n: int,
    pipeline: list[dict[str, Any]],
    cache_enabled: bool,
    corpus_cache_token: str | None,
    score_calibration_enabled: bool,
    score_calibration_alpha: float,
    score_calibration_stats: dict[str, Any],
) -> dict[str, Any]:
    return _run_post_rerank_pipeline_mode_impl(
        state=state,
        docs=docs,
        query_for_retrieval=query_for_retrieval,
        top_n=top_n,
        pipeline=pipeline,
        cache_enabled=cache_enabled,
        corpus_cache_token=corpus_cache_token,
        score_calibration_enabled=score_calibration_enabled,
        score_calibration_alpha=score_calibration_alpha,
        score_calibration_stats=score_calibration_stats,
        build_candidates_fn=_build_post_rerank_candidates,
        get_cached_result_fn=_get_cached_post_rerank_result,
        execute_post_rerank_fn=_execute_post_rerank,
        build_reranked_prefix_fn=_build_reranked_prefix,
        calibrate_prefix_fn=_calibrate_post_rerank_prefix_docs,
    )


def _run_post_rerank_stage(
    *,
    state: dict[str, Any],
    docs: list[Document],
    query_for_retrieval: str,
    top_k: int,
) -> dict[str, Any]:
    settings_meta = _post_rerank_settings(state)
    return _run_post_rerank_stage_impl(
        state=state,
        docs=docs,
        query_for_retrieval=query_for_retrieval,
        top_k=top_k,
        settings_meta=settings_meta,
        pipeline_summary_fn=_safe_post_rerank_pipeline_summary,
        pipeline_mode_fn=_run_post_rerank_pipeline_mode,
        single_mode_fn=_run_post_rerank_single_mode,
        fallback_logger_fn=_log_orchestrator_fallback,
    )


def _safe_kg_path_provenance(raw: Any) -> dict[str, Any] | None:
    return _safe_kg_path_provenance_impl(raw)


def _build_desired_pipeline_by_doc(docs: list[Document]) -> dict[str, str]:
    return _build_desired_pipeline_by_doc_impl(docs)


def _hierarchy_fetch_pairs_by_doc(
    pairs: set[tuple[str, str]],
) -> dict[str, set[str]]:
    return _hierarchy_fetch_pairs_by_doc_impl(pairs)


def _chunk_document_from_row(ck: Any) -> Document | None:
    return _chunk_document_from_row_impl(ck)


def _fetch_hierarchy_expansion_docs(
    pairs: set[tuple[str, str]],
    *,
    tenant_uuid: UUID | None,
    desired_pipeline_by_doc: dict[str, str],
) -> dict[tuple[str, str], Document]:
    return _fetch_hierarchy_expansion_docs_impl(
        pairs,
        tenant_uuid=tenant_uuid,
        desired_pipeline_by_doc=desired_pipeline_by_doc,
    )


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
        "docs": list(docs or []),
        "hierarchy_expand_attempted": False,
        "hierarchy_expand_used": False,
        "hierarchy_expand_error": None,
        "hierarchy_expand_elapsed": 0.0,
        "hierarchy_expand_meta": {"enabled": False, "reason": "not_run"},
    }
    if not (
        bool(hierarchy_recall_enabled)
        and bool(docs)
        and (int(hierarchy_parent_depth) > 0 or int(hierarchy_sibling_window) > 0)
    ):
        return result

    result["hierarchy_expand_attempted"] = True
    exp_start = time.time()
    try:
        tenant_uuid: UUID | None = None
        try:
            tenant_id_raw = state.get("tenant_id")
            if tenant_id_raw is not None:
                tenant_uuid = UUID(str(tenant_id_raw))
        except (TypeError, ValueError, AttributeError):
            tenant_uuid = None

        from app.rag.retrieval.context_expansion import expand_hierarchy_documents  # noqa: WPS433

        desired_pipeline_by_doc = _build_desired_pipeline_by_doc(docs)
        max_added = max(
            0,
            int(top_k) * (int(hierarchy_parent_depth) + (2 * int(hierarchy_sibling_window))),
        )
        max_added = min(400, max_added or 120)
        expanded_docs, meta = expand_hierarchy_documents(
            [doc for doc in (docs or []) if doc is not None],
            parent_depth=int(hierarchy_parent_depth),
            sibling_window=int(hierarchy_sibling_window),
            fetch_by_key=lambda pairs: _fetch_hierarchy_expansion_docs(
                pairs,
                tenant_uuid=tenant_uuid,
                desired_pipeline_by_doc=desired_pipeline_by_doc,
            ),
            max_added_docs=int(max_added),
        )
        result["hierarchy_expand_elapsed"] = max(0.0, float(time.time() - exp_start))
        if isinstance(meta, dict):
            result["hierarchy_expand_meta"] = dict(meta)
        else:
            result["hierarchy_expand_meta"] = {"enabled": False, "reason": "invalid_meta"}
        if expanded_docs and int((result["hierarchy_expand_meta"] or {}).get("added_docs") or 0) > 0:
            result["docs"] = expanded_docs
            result["hierarchy_expand_used"] = True
        return result
    except Exception as exc:  # noqa: BLE001
        _log_orchestrator_fallback("_run_hierarchy_expansion_stage", exc)
        result["hierarchy_expand_error"] = str(exc)[:200]
        result["hierarchy_expand_meta"] = {"enabled": False, "reason": "exception"}
        return result


def _filter_strict_span_citations(
    items: list[dict[str, Any]],
    *,
    enabled: bool,
) -> tuple[list[dict[str, Any]], int]:
    if not enabled or not items:
        return items, 0
    filtered_items: list[dict[str, Any]] = []
    missing_count = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        start = item.get("evidence_start_char")
        end = item.get("evidence_end_char")
        try:
            start_i = int(start) if start is not None else None
            end_i = int(end) if end is not None else None
        except (TypeError, ValueError, AttributeError):
            start_i = None
            end_i = None
        if start_i is None or end_i is None or end_i <= start_i:
            missing_count += 1
            continue
        filtered_items.append(item)
    return filtered_items, missing_count


def _prepare_query_phase(
    state: dict[str, Any],
    *,
    question: str,
    history_text: str,
    llm_engine_factory: Any,
) -> dict[str, Any]:
    from app.rag.retrieval.sparse import normalize_sparse_provider_name

    query_for_retrieval = question
    rewrite_elapsed = 0.0
    rewrite_used = False
    rewrite_model_used = None
    rewrite_strategy_id: str | None = None
    rewrite_strategy_hash: str | None = None
    rewrite_temperature: float | None = None
    rewrite_max_chars: int | None = None

    sparse_enabled_override = state.get("sparse_retrieval_enabled")
    sparse_enabled = (
        bool(sparse_enabled_override)
        if sparse_enabled_override is not None
        else bool(getattr(settings, "SPARSE_RETRIEVAL_ENABLED", False))
    )
    sparse_provider_raw = state.get("sparse_retrieval_provider")
    sparse_provider = normalize_sparse_provider_name(
        str(
            sparse_provider_raw
            if sparse_provider_raw is not None
            else (getattr(settings, "SPARSE_RETRIEVAL_PROVIDER", "deterministic") or "deterministic")
        )
    )

    industry_rules_meta: dict[str, Any] = {"enabled": False, "used": False}
    temporal_intent_enabled = bool(getattr(settings, "RAG_TEMPORAL_INTENT_ENABLED", False))
    temporal_intent_meta: dict[str, Any] = {"detected": False, "reason_codes": []}
    temporal_recency_meta: dict[str, Any] = {"enabled": False, "used": False, "reason": "not_run"}

    rewrite_enabled_req = state.get("enable_query_rewrite")
    rewrite_enabled = (
        bool(rewrite_enabled_req) if rewrite_enabled_req is not None else bool(settings.ENABLE_QUERY_REWRITE)
    )
    if rewrite_enabled:
        spec = build_query_rewrite_strategy_spec(
            state.get("query_rewrite_strategy") or getattr(settings, "QUERY_REWRITE_STRATEGY", None)
        )
        rewrite_strategy_id = str(spec.get("strategy_id") or "").strip() or None
        rewrite_strategy_hash = str(spec.get("strategy_hash") or "").strip() or None
        try:
            rewrite_temperature = float(
                (
                    settings.QUERY_REWRITE_TEMPERATURE
                    if state.get("query_rewrite_temperature") is None
                    else state.get("query_rewrite_temperature")
                )
                or 0.0
            )
        except (TypeError, ValueError, AttributeError):
            rewrite_temperature = 0.0
        try:
            rewrite_max_chars = int(
                (
                    settings.QUERY_REWRITE_MAX_CHARS
                    if state.get("query_rewrite_max_chars") is None
                    else state.get("query_rewrite_max_chars")
                )
                or 0
            )
        except (TypeError, ValueError, AttributeError):
            rewrite_max_chars = 0

    if (
        bool(rewrite_enabled)
        and history_text != "(No conversation history)"
        and len(question) <= int(rewrite_max_chars or 0)
        and should_rewrite_query(question)
    ):
        rewrite_engine = llm_engine_factory()
        rewrite_llm = rewrite_engine.models.get("fast") or rewrite_engine.models.get("default")  # type: ignore[attr-defined]
        rewrite_model_used = getattr(rewrite_llm, "model_name", None) or getattr(rewrite_llm, "model", None)
        try:
            chat_prompt_template_cls, str_output_parser_cls = _get_langchain_text_pipeline_primitives()
            prompt_template = get_query_rewrite_prompt_template(rewrite_strategy_id)
            rewrite_prompt = chat_prompt_template_cls.from_template(prompt_template)
            rewrite_chain = rewrite_prompt | rewrite_llm.bind(temperature=rewrite_temperature) | str_output_parser_cls()
            rewrite_start = time.time()
            rewritten = rewrite_chain.invoke({"history": history_text, "question": question})
            rewrite_elapsed = time.time() - rewrite_start
            rewritten = (rewritten or "").strip().strip('"')
            if rewritten:
                query_for_retrieval = rewritten
        except Exception as exc:  # noqa: BLE001
            _log_orchestrator_fallback("_prepare_query_phase", exc)
            query_for_retrieval = question
            rewrite_elapsed = 0.0
        rewrite_used = query_for_retrieval != question

    industry_rules_enabled_req = state.get("industry_rules_enabled")
    industry_rules_enabled = (
        bool(industry_rules_enabled_req)
        if industry_rules_enabled_req is not None
        else bool(getattr(settings, "RAG_INDUSTRY_RULES_ENABLED", False))
    )
    try:
        query_for_retrieval, industry_rules_meta = apply_industry_rules_query_expansion(
            query_for_retrieval,
            enabled=industry_rules_enabled,
            ruleset_names=(
                state.get("industry_rules_rulesets")
                if state.get("industry_rules_rulesets") is not None
                else getattr(settings, "RAG_INDUSTRY_RULES_RULESETS", "")
            ),
            max_aliases=int(getattr(settings, "RAG_INDUSTRY_RULES_MAX_ALIASES", 16) or 16),
            max_query_chars=int(getattr(settings, "RAG_INDUSTRY_RULES_MAX_QUERY_CHARS", 2000) or 2000),
        )
    except Exception as exc:  # noqa: BLE001
        _log_orchestrator_fallback("_prepare_query_phase", exc)
        industry_rules_meta = {
            "enabled": bool(industry_rules_enabled),
            "used": False,
            "error": f"industry_rules_exception:{str(exc)[:160]}",
        }

    if temporal_intent_enabled:
        try:
            temporal_intent_meta = detect_temporal_intent(query_for_retrieval)
        except Exception as exc:  # noqa: BLE001
            _log_orchestrator_fallback("_prepare_query_phase", exc)
            temporal_intent_meta = {"detected": False, "reason_codes": [], "error": str(exc)[:200]}

    return {
        "query_for_retrieval": query_for_retrieval,
        "rewrite_elapsed": rewrite_elapsed,
        "rewrite_used": rewrite_used,
        "rewrite_model_used": rewrite_model_used,
        "rewrite_strategy_id": rewrite_strategy_id,
        "rewrite_strategy_hash": rewrite_strategy_hash,
        "rewrite_temperature": rewrite_temperature,
        "rewrite_max_chars": rewrite_max_chars,
        "rewrite_enabled": rewrite_enabled,
        "sparse_enabled": sparse_enabled,
        "sparse_provider": sparse_provider,
        "industry_rules_meta": industry_rules_meta,
        "temporal_intent_enabled": temporal_intent_enabled,
        "temporal_intent_meta": temporal_intent_meta,
        "temporal_recency_meta": temporal_recency_meta,
    }


def _resolve_contract_phase(
    state: dict[str, Any],
    *,
    query_for_retrieval: str,
) -> dict[str, Any]:
    return _resolve_contract_phase_impl(
        state,
        query_for_retrieval=query_for_retrieval,
        resolve_retrieval_contract_policy_fn=resolve_retrieval_contract_policy,
        infer_expected_source_keys_fn=infer_expected_source_keys,
        infer_required_anchor_fields_fn=infer_required_anchor_fields,
    )


def _apply_routing_phase(
    state: dict[str, Any],
    *,
    query_for_retrieval: str,
    requested_retrieval_mode: Any,
    requested_retrieval_profile: Any,
    sparse_enabled: bool,
    sparse_provider: str,
    hierarchy_recall_enabled: bool,
    hierarchy_family_collapse: bool,
    hierarchy_family_aggregation: str,
    hierarchy_tree_dedup: bool,
    hierarchy_parent_depth: int,
    hierarchy_sibling_window: int,
    hierarchy_overfetch_factor: int,
) -> dict[str, Any]:
    return _apply_routing_phase_impl(
        state,
        query_for_retrieval=query_for_retrieval,
        requested_retrieval_mode=requested_retrieval_mode,
        requested_retrieval_profile=requested_retrieval_profile,
        sparse_enabled=sparse_enabled,
        sparse_provider=sparse_provider,
        hierarchy_recall_enabled=hierarchy_recall_enabled,
        hierarchy_family_collapse=hierarchy_family_collapse,
        hierarchy_family_aggregation=hierarchy_family_aggregation,
        hierarchy_tree_dedup=hierarchy_tree_dedup,
        hierarchy_parent_depth=hierarchy_parent_depth,
        hierarchy_sibling_window=hierarchy_sibling_window,
        hierarchy_overfetch_factor=hierarchy_overfetch_factor,
        hybrid_retriever_obj=hybrid_retriever,
        route_retrieval_preset_fn=route_retrieval_preset,
        route_adaptive_retrieval_overrides_fn=route_adaptive_retrieval_overrides,
    )


def _run_retrieval_bootstrap_phase(ctx: RetrievalRuntimeState) -> dict[str, Any] | None:
    ctx.engine: Any | None = None

    def _llm_engine() -> Any:
        if ctx.engine is None:
            ctx.engine = get_rag_engine()
        return ctx.engine

    ctx._llm_engine = _llm_engine

    # KG search output can be reused by multiple retrieval steps (query expansion / chunk injection).
    ctx.kg_result_cached: dict[str, Any] | None = None
    ctx.intent_router_meta: dict[str, Any] = {"enabled": False, "used": False}
    ctx.adaptive_router_meta: dict[str, Any] = {"enabled": False, "used": False}
    ctx.channel_budget_policy_meta: dict[str, Any] = {"enabled": False, "used": False}
    query_phase = _prepare_query_phase(
        ctx.state,
        question=ctx.question,
        history_text=ctx.history_text,
        llm_engine_factory=_llm_engine,
    )
    ctx.query_for_retrieval = str(query_phase["query_for_retrieval"])
    ctx.rewrite_elapsed = float(query_phase["rewrite_elapsed"])
    ctx.rewrite_used = bool(query_phase["rewrite_used"])
    ctx.rewrite_model_used = query_phase["rewrite_model_used"]
    ctx.rewrite_strategy_id = query_phase["rewrite_strategy_id"]
    ctx.rewrite_strategy_hash = query_phase["rewrite_strategy_hash"]
    ctx.rewrite_temperature = query_phase["rewrite_temperature"]
    ctx.rewrite_max_chars = query_phase["rewrite_max_chars"]
    ctx.rewrite_enabled = bool(query_phase["rewrite_enabled"])
    ctx.sparse_enabled = bool(query_phase["sparse_enabled"])
    ctx.sparse_provider = str(query_phase["sparse_provider"] or "")
    ctx.industry_rules_meta = dict(query_phase["industry_rules_meta"])
    ctx.temporal_intent_enabled = bool(query_phase["temporal_intent_enabled"])
    ctx.temporal_intent_meta = dict(query_phase["temporal_intent_meta"])
    ctx.temporal_recency_meta = dict(query_phase["temporal_recency_meta"])

    contract_phase = _resolve_contract_phase(
        ctx.state,
        query_for_retrieval=ctx.query_for_retrieval,
    )
    ctx.requested_retrieval_mode = contract_phase["requested_retrieval_mode"]
    ctx.requested_retrieval_profile = contract_phase["requested_retrieval_profile"]
    ctx.retrieval_contract_policy = dict(contract_phase["retrieval_contract_policy"])
    ctx.retrieval_contract_mode = str(contract_phase["retrieval_contract_mode"])
    ctx.contract_deterministic_recall = bool(contract_phase["contract_deterministic_recall"])
    ctx.contract_must_recall_strict = bool(contract_phase["contract_must_recall_strict"])
    ctx.must_recall_requested = contract_phase["must_recall_requested"]
    ctx.must_recall_enabled = bool(contract_phase["must_recall_enabled"])
    ctx.must_recall_expected_source_keys = list(contract_phase["must_recall_expected_source_keys"])
    ctx.must_recall_auto_expected_source_keys_enabled = bool(
        contract_phase["must_recall_auto_expected_source_keys_enabled"]
    )
    ctx.must_recall_auto_expected_source_keys = list(contract_phase["must_recall_auto_expected_source_keys"])
    ctx.must_recall_auto_expected_source_keys_reason_codes = list(
        contract_phase["must_recall_auto_expected_source_keys_reason_codes"]
    )
    ctx.must_recall_auto_expected_source_keys_confidence = str(
        contract_phase["must_recall_auto_expected_source_keys_confidence"]
    )
    ctx.must_recall_auto_expected_source_keys_applied = bool(
        contract_phase["must_recall_auto_expected_source_keys_applied"]
    )
    ctx.must_recall_required_anchor_fields = list(contract_phase["must_recall_required_anchor_fields"])
    ctx.must_recall_auto_required_anchor_fields_enabled = bool(
        contract_phase["must_recall_auto_required_anchor_fields_enabled"]
    )
    ctx.must_recall_auto_required_anchor_fields = list(contract_phase["must_recall_auto_required_anchor_fields"])
    ctx.must_recall_auto_required_anchor_fields_reason_codes = list(
        contract_phase["must_recall_auto_required_anchor_fields_reason_codes"]
    )
    ctx.must_recall_auto_required_anchor_fields_applied = bool(
        contract_phase["must_recall_auto_required_anchor_fields_applied"]
    )
    ctx.must_recall_second_pass_enabled = bool(contract_phase["must_recall_second_pass_enabled"])
    ctx.must_recall_second_pass_mode = str(contract_phase["must_recall_second_pass_mode"])
    ctx.must_recall_second_pass_top_k = int(contract_phase["must_recall_second_pass_top_k"])
    ctx.contextual_followup_enabled = bool(contract_phase["contextual_followup_enabled"])
    ctx.contextual_followup_mode = str(contract_phase["contextual_followup_mode"])
    ctx.contextual_followup_top_k = int(contract_phase["contextual_followup_top_k"])
    ctx.contextual_followup_max_docs = int(contract_phase["contextual_followup_max_docs"])
    ctx.contextual_followup_max_terms = int(contract_phase["contextual_followup_max_terms"])
    ctx.contextual_followup_min_term_chars = int(contract_phase["contextual_followup_min_term_chars"])
    ctx.contextual_followup_max_query_chars = int(contract_phase["contextual_followup_max_query_chars"])
    ctx.contextual_followup_max_hops = int(contract_phase["contextual_followup_max_hops"])
    ctx.contextual_followup_latency_budget_ms = float(contract_phase["contextual_followup_latency_budget_ms"])
    ctx.hierarchy_recall_enabled = bool(contract_phase["hierarchy_recall_enabled"])
    ctx.hierarchy_family_collapse = bool(contract_phase["hierarchy_family_collapse"])
    ctx.hierarchy_family_aggregation = str(contract_phase["hierarchy_family_aggregation"])
    ctx.hierarchy_tree_dedup = bool(contract_phase["hierarchy_tree_dedup"])
    ctx.hierarchy_parent_depth = int(contract_phase["hierarchy_parent_depth"])
    ctx.hierarchy_sibling_window = int(contract_phase["hierarchy_sibling_window"])
    ctx.hierarchy_overfetch_factor = int(contract_phase["hierarchy_overfetch_factor"])

    routing_phase = _apply_routing_phase(
        ctx.state,
        query_for_retrieval=ctx.query_for_retrieval,
        requested_retrieval_mode=ctx.requested_retrieval_mode,
        requested_retrieval_profile=ctx.requested_retrieval_profile,
        sparse_enabled=bool(ctx.sparse_enabled),
        sparse_provider=str(ctx.sparse_provider or ""),
        hierarchy_recall_enabled=bool(ctx.hierarchy_recall_enabled),
        hierarchy_family_collapse=bool(ctx.hierarchy_family_collapse),
        hierarchy_family_aggregation=str(ctx.hierarchy_family_aggregation),
        hierarchy_tree_dedup=bool(ctx.hierarchy_tree_dedup),
        hierarchy_parent_depth=int(ctx.hierarchy_parent_depth),
        hierarchy_sibling_window=int(ctx.hierarchy_sibling_window),
        hierarchy_overfetch_factor=int(ctx.hierarchy_overfetch_factor),
    )
    ctx.intent_router_meta = dict(routing_phase["intent_router_meta"])
    ctx.adaptive_router_meta = dict(routing_phase["adaptive_router_meta"])
    ctx.channel_budget_policy_meta = dict(routing_phase["channel_budget_policy_meta"])
    ctx.request_retrieval_mode = str(routing_phase["request_retrieval_mode"])
    ctx.retrieval_mode_routed = bool(routing_phase["retrieval_mode_routed"])
    ctx.profile_norm = str(routing_phase["profile_norm"] or "")
    ctx.retrieval_contract_policy = dict(routing_phase["retrieval_contract_policy"])
    ctx.retrieval_contract_mode = str(routing_phase["retrieval_contract_mode"])
    ctx.contract_deterministic_recall = bool(routing_phase["contract_deterministic_recall"])
    ctx.sparse_enabled = bool(routing_phase["sparse_enabled"])
    ctx.sparse_provider = str(routing_phase["sparse_provider"] or "")
    ctx.hierarchy_recall_enabled = bool(routing_phase["hierarchy_recall_enabled"])
    ctx.hierarchy_family_collapse = bool(routing_phase["hierarchy_family_collapse"])
    ctx.hierarchy_family_aggregation = str(routing_phase["hierarchy_family_aggregation"])
    ctx.hierarchy_tree_dedup = bool(routing_phase["hierarchy_tree_dedup"])
    ctx.hierarchy_parent_depth = int(routing_phase["hierarchy_parent_depth"])
    ctx.hierarchy_sibling_window = int(routing_phase["hierarchy_sibling_window"])
    ctx.hierarchy_overfetch_factor = int(routing_phase["hierarchy_overfetch_factor"])
    ctx.retriever_update = dict(routing_phase["retriever_update"])
    ctx.retriever = routing_phase["retriever"]
    return None


def _run_retrieval_alias_dictionary_phase(ctx: RetrievalRuntimeState) -> dict[str, Any] | None:
    ctx.alias_elapsed = 0.0
    ctx.alias_used = False
    ctx.alias_meta: dict[str, Any] = {"enabled": False, "used": False}
    ctx.alias_queries: list[str] = []

    ctx.alias_enabled = ctx.state.get("enable_query_alias_expansion")
    aliases = ctx.state.get("query_aliases")
    if ctx.alias_enabled is None:
        ctx.alias_enabled = bool(aliases)
    if bool(ctx.alias_enabled):
        t0 = time.time()
        ctx.alias_queries, ctx.alias_meta = generate_alias_queries(
            query=ctx.query_for_retrieval,
            aliases=aliases,
            max_queries=(
                5
                if ctx.state.get("query_alias_max_queries") is None
                else int(ctx.state.get("query_alias_max_queries") or 0)
            ),
        )
        ctx.alias_elapsed = time.time() - t0
        ctx.alias_used = bool(ctx.alias_queries)

    # Deterministic dictionary expansion (bounded, auditable).
    ctx.dict_elapsed = 0.0
    ctx.dict_used = False
    ctx.dict_meta: dict[str, Any] = {"enabled": False, "used": False}
    ctx.dict_expansions: list[dict[str, Any]] = []
    try:
        from app.query.expand import generate_dictionary_expansions, load_base_dictionary_rules

        t0 = time.time()
        ctx.dict_expansions, ctx.dict_meta = generate_dictionary_expansions(
            query=ctx.query_for_retrieval,
            rules=load_base_dictionary_rules(),
            max_expansions_total=5,
            max_expansions_per_rule=1,
        )
        ctx.dict_elapsed = time.time() - t0
        ctx.dict_used = bool(ctx.dict_expansions)
    except Exception as exc:  # noqa: BLE001
        _log_orchestrator_fallback("run_retrieval", exc)
        ctx.dict_elapsed = 0.0
        ctx.dict_used = False
        ctx.dict_expansions = []
        ctx.dict_meta = {"enabled": False, "used": False, "error": str(exc)[:200]}
    return None


def _run_kg_search_sync(kg_kwargs: dict[str, Any]) -> Any:
    coro = kg_search(**kg_kwargs)
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = None
    if loop is not None and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    if loop is not None:
        return loop.run_until_complete(coro)
    return asyncio.run(coro)


def _score_kg_query_entities(
    entities: list[Any],
    *,
    exclude_all: bool,
    exclude_fold: set[str],
    min_weight: float,
) -> list[tuple[float, str]]:
    scored: list[tuple[float, str]] = []
    for entity in entities:
        if not isinstance(entity, dict) or exclude_all:
            continue
        entity_type = str(entity.get("type") or "").strip()
        if entity_type and entity_type.casefold() in exclude_fold:
            continue
        name = str(entity.get("name") or "").strip()
        if not name:
            continue
        try:
            weight = float(entity.get("weight", 0.0) or 0.0)
        except (TypeError, ValueError, AttributeError):
            weight = 0.0
        if weight >= min_weight:
            scored.append((weight, name))
    return sorted(scored, key=lambda item: (-item[0], item[1]))


def _select_kg_query_entity_names(
    scored: list[tuple[float, str]],
    *,
    query: str,
    max_entities: int,
) -> list[str]:
    seen_names: set[str] = set()
    base_folded = query.casefold()
    selected_names: list[str] = []
    for _weight, name in scored:
        key = name.casefold() if name.isascii() else name
        if key in seen_names:
            continue
        seen_names.add(key)
        if key and key in base_folded:
            continue
        selected_names.append(name)
        if max_entities > 0 and len(selected_names) >= max_entities:
            break
    return selected_names


def _build_kg_query_expansions(query: str, names: list[str], *, max_queries: int) -> list[str]:
    queries: list[str] = []
    for name in names:
        expanded = f"{query} {name}".strip()
        if len(expanded) > 500:
            expanded = expanded[:500] + "..."
        queries.append(expanded)
        if max_queries > 0 and len(queries) >= max_queries:
            break
    return queries


def _run_retrieval_kg_query_expansion_phase(ctx: RetrievalRuntimeState) -> dict[str, Any] | None:
    ctx.kg_query_expansion_enabled = _coerce_optional_bool(
        ctx.state.get("enable_kg_query_expansion"),
        default=bool(getattr(settings, "RAG_KG_QUERY_EXPANSION_ENABLED", False)),
    )
    ctx.kg_query_expansion_used = False
    ctx.kg_query_expansion_elapsed = 0.0
    ctx.kg_query_expansion_error: str | None = None
    ctx.kg_query_expansion_entities_total = 0
    ctx.kg_query_expansion_entities_selected = 0
    ctx.kg_query_expansion_queries: list[str] = []
    ctx.kg_query_expansion_entity_names: list[str] = []
    try:
        tenant_id = ctx.state.get("tenant_id")
        account_id = ctx.state.get("account_id")
        kg_document_ids, kg_dataset_id, kg_dataset_ids = _resolve_kg_scope(ctx.state)

        if (
            ctx.kg_query_expansion_enabled
            and bool(getattr(settings, "KG_ENABLED", False))
            and bool(getattr(settings, "KG_CHAT_ENABLED", False))
            and tenant_id is not None
            and (kg_document_ids or kg_dataset_id is not None or kg_dataset_ids)
            and (account_id is not None or (kg_dataset_id is None and not kg_dataset_ids))
        ):
            kg_kwargs = {
                "query": ctx.query_for_retrieval,
                "tenant_id": tenant_id,
                "document_ids": kg_document_ids or None,
                "dataset_id": kg_dataset_id,
                "account_id": account_id,
            }
            if kg_dataset_ids:
                kg_kwargs["dataset_ids"] = kg_dataset_ids
            t0 = time.time()
            kg_result = _run_kg_search_sync(kg_kwargs)

            ctx.kg_result_cached = kg_result if isinstance(kg_result, dict) else None
            ctx.kg_query_expansion_elapsed = time.time() - t0

            entities = (kg_result or {}).get("entities") or []
            entities = entities if isinstance(entities, list) else []
            ctx.kg_query_expansion_entities_total = len(entities)

            max_entities = max(0, int(getattr(settings, "RAG_KG_QUERY_EXPANSION_MAX_ENTITIES", 5) or 5))
            max_queries = max(0, int(getattr(settings, "RAG_KG_QUERY_EXPANSION_MAX_QUERIES", 5) or 5))
            min_weight = float(getattr(settings, "RAG_KG_QUERY_EXPANSION_MIN_ENTITY_WEIGHT", 0.15) or 0.15)
            exclude_types = parse_csv(str(getattr(settings, "RAG_KG_QUERY_EXPANSION_EXCLUDE_ENTITY_TYPES", "") or ""))
            exclude_all = "*" in exclude_types
            exclude_fold = {t.casefold() for t in exclude_types if str(t or "").strip() and t != "*"}

            scored = _score_kg_query_entities(
                entities,
                exclude_all=exclude_all,
                exclude_fold=exclude_fold,
                min_weight=min_weight,
            )
            selected_names = _select_kg_query_entity_names(
                scored,
                query=ctx.query_for_retrieval,
                max_entities=max_entities,
            )

            ctx.kg_query_expansion_entities_selected = len(selected_names)
            ctx.kg_query_expansion_entity_names = selected_names[
                : max_queries if max_queries > 0 else len(selected_names)
            ]

            ctx.kg_query_expansion_queries = _build_kg_query_expansions(
                ctx.query_for_retrieval,
                ctx.kg_query_expansion_entity_names,
                max_queries=max_queries,
            )

            ctx.kg_query_expansion_used = bool(ctx.kg_query_expansion_queries)
    except Exception as exc:  # noqa: BLE001
        _log_orchestrator_fallback("run_retrieval", exc)
        ctx.kg_query_expansion_used = False
        ctx.kg_query_expansion_queries = []
        ctx.kg_query_expansion_entity_names = []
        ctx.kg_query_expansion_error = str(exc)[:200]
    return None


def _normalize_multi_queries(raw: Any, *, query: str, limit: int) -> list[str]:
    if not isinstance(raw, list):
        return []
    seen: set[str] = set()
    queries: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            continue
        candidate = item.strip().strip('"').strip()
        if not candidate or candidate == query or candidate in seen:
            continue
        if len(candidate) > 400:
            candidate = candidate[:400] + "..."
        seen.add(candidate)
        queries.append(candidate)
        if len(queries) >= limit:
            break
    return queries


def _run_retrieval_multi_query_phase(ctx: RetrievalRuntimeState) -> dict[str, Any] | None:
    ctx.multi_query_elapsed = 0.0
    ctx.multi_query_used = False
    ctx.multi_query_model_used = None
    ctx.multi_query_parse_meta: dict[str, Any] = {"ok": False, "method": None, "error": None}
    ctx.multi_queries: list[str] = []
    ctx.multi_query_ab_test_key = str(ctx.state.get("multi_query_ab_test_key") or "").strip() or None
    ctx.multi_query_ab_variant = str(ctx.state.get("multi_query_ab_variant") or "").strip().lower() or None
    ctx.multi_query_ab_seed = ctx.state.get("multi_query_ab_seed")
    ctx.multi_query_ab_forced = bool(
        ctx.state.get("enable_multi_query") is None
        and ctx.multi_query_ab_variant in {"on", "enabled", "treatment", "mq"}
    )

    ctx.mq_enabled = (
        bool(ctx.state.get("enable_multi_query"))
        if ctx.state.get("enable_multi_query") is not None
        else (bool(settings.ENABLE_MULTI_QUERY) or ctx.multi_query_ab_forced)
    )
    ctx.mq_n = (
        settings.MULTI_QUERY_COUNT
        if ctx.state.get("multi_query_count") is None
        else int(ctx.state.get("multi_query_count") or 0)
    )
    ctx.mq_temp = (
        settings.MULTI_QUERY_TEMPERATURE
        if ctx.state.get("multi_query_temperature") is None
        else float(ctx.state.get("multi_query_temperature") or 0.0)
    )
    ctx.mq_max_chars = (
        settings.MULTI_QUERY_MAX_CHARS
        if ctx.state.get("multi_query_max_chars") is None
        else int(ctx.state.get("multi_query_max_chars") or 0)
    )

    mq_cap = max(0, int(getattr(settings, "MULTI_QUERY_COUNT_CAP", 8) or 8))
    ctx.mq_n = max(0, min(int(ctx.mq_n or 0), int(mq_cap)))
    ctx.mq_temp = min(2.0, max(0.0, float(ctx.mq_temp or 0.0)))
    ctx.mq_max_chars = max(0, int(ctx.mq_max_chars or 0))

    if ctx.mq_enabled and ctx.mq_n > 0 and ctx.mq_max_chars > 0 and len(ctx.query_for_retrieval) <= ctx.mq_max_chars:
        mq_engine = ctx._llm_engine()
        mq_llm = mq_engine.models.get("fast") or mq_engine.models.get("default")  # type: ignore[attr-defined]
        ctx.multi_query_model_used = getattr(mq_llm, "model_name", None) or getattr(mq_llm, "model", None)
        try:
            _, str_output_parser_cls = _get_langchain_text_pipeline_primitives()
            mq_chain = (
                mq_engine.multi_query_prompt  # type: ignore[attr-defined]
                | mq_llm.bind(temperature=ctx.mq_temp)
                | str_output_parser_cls()
            )
            mq_start = time.time()
            mq_raw = mq_chain.invoke({"query": ctx.query_for_retrieval, "n": ctx.mq_n})
            ctx.multi_query_elapsed = time.time() - mq_start
            mq_data, ctx.multi_query_parse_meta = parse_json_from_text(mq_raw, expected="array")

            ctx.multi_queries = _normalize_multi_queries(
                mq_data,
                query=ctx.query_for_retrieval,
                limit=ctx.mq_n,
            )
            if ctx.multi_query_ab_seed is not None and ctx.multi_queries:
                seed_prefix = str(ctx.multi_query_ab_seed)
                ctx.multi_queries = sorted(
                    ctx.multi_queries,
                    key=lambda item: (
                        stable_hash(f"{seed_prefix}:{item}", length=16),
                        item,
                    ),
                )
        except Exception as exc:  # noqa: BLE001
            _log_orchestrator_fallback("run_retrieval", exc)
            ctx.multi_query_elapsed = 0.0
            ctx.multi_query_parse_meta = {"ok": False, "method": None, "error": str(exc)[:200]}
            ctx.multi_queries = []

    ctx.multi_query_used = bool(ctx.multi_queries)
    return None


def _run_retrieval_hyde_phase(ctx: RetrievalRuntimeState) -> dict[str, Any] | None:
    ctx.hyde_used = False
    ctx.hyde_elapsed = 0.0
    ctx.hyde_model_used = None
    ctx.hyde_text = ""
    hyde_max_chars = max(0, int(settings.HYDE_MAX_CHARS or 0))
    retrieval_mode_norm = str(ctx.request_retrieval_mode or "hybrid").lower()
    ctx.hyde_enabled = (
        bool(settings.ENABLE_HYDE) if ctx.state.get("enable_hyde") is None else bool(ctx.state.get("enable_hyde"))
    )
    if (
        ctx.hyde_enabled
        and retrieval_mode_norm not in ("keyword",)
        and hyde_max_chars > 0
        and len(ctx.query_for_retrieval) <= hyde_max_chars
    ):
        hyde_engine = ctx._llm_engine()
        hyde_llm = hyde_engine.models.get("fast") or hyde_engine.models.get("default")  # type: ignore[attr-defined]
        ctx.hyde_model_used = getattr(hyde_llm, "model_name", None) or getattr(hyde_llm, "model", None)
        try:
            _, str_output_parser_cls = _get_langchain_text_pipeline_primitives()
            hyde_chain = (
                hyde_engine.hyde_prompt  # type: ignore[attr-defined]
                | hyde_llm.bind(temperature=settings.HYDE_TEMPERATURE)
                | str_output_parser_cls()
            )
            hyde_start = time.time()
            ctx.hyde_text = hyde_chain.invoke({"query": ctx.query_for_retrieval})
            ctx.hyde_elapsed = time.time() - hyde_start
            ctx.hyde_text = (ctx.hyde_text or "").strip()
            out_max = max(0, int(settings.HYDE_OUTPUT_MAX_CHARS or 0))
            if out_max and len(ctx.hyde_text) > out_max:
                ctx.hyde_text = ctx.hyde_text[:out_max] + "..."
            ctx.hyde_used = bool(ctx.hyde_text)
        except Exception as exc:
            _log_orchestrator_fallback("run_retrieval", exc)
            ctx.hyde_text = ""
            ctx.hyde_elapsed = 0.0
            ctx.hyde_used = False
    return None


def _run_retrieval_step_back_phase(ctx: RetrievalRuntimeState) -> dict[str, Any] | None:
    ctx.step_back_enabled = bool(getattr(settings, "ENABLE_STEP_BACK_QUERY", False))
    ctx.step_back_elapsed = 0.0
    ctx.step_back_used = False
    ctx.step_back_model_used = None
    ctx.step_back_parse_meta: dict[str, Any] = {"ok": False, "method": None, "error": None}
    ctx.step_back_query = ""
    ctx.step_back_max_chars = max(0, int(getattr(settings, "STEP_BACK_MAX_CHARS", 0) or 0))
    ctx.step_back_temp = min(2.0, max(0.0, float(getattr(settings, "STEP_BACK_TEMPERATURE", 0.2) or 0.0)))
    ctx.step_back_output_max = max(0, int(getattr(settings, "STEP_BACK_OUTPUT_MAX_CHARS", 0) or 0))
    if (
        ctx.step_back_enabled
        and ctx.step_back_max_chars > 0
        and len(ctx.query_for_retrieval) <= ctx.step_back_max_chars
    ):
        step_back_engine = ctx._llm_engine()
        sb_llm = step_back_engine.models.get("fast") or step_back_engine.models.get("default")  # type: ignore[attr-defined]
        ctx.step_back_model_used = getattr(sb_llm, "model_name", None) or getattr(sb_llm, "model", None)
        try:
            _, str_output_parser_cls = _get_langchain_text_pipeline_primitives()
            sb_chain = (
                step_back_engine.step_back_prompt  # type: ignore[attr-defined]
                | sb_llm.bind(temperature=ctx.step_back_temp)
                | str_output_parser_cls()
            )
            sb_start = time.time()
            sb_raw = sb_chain.invoke({"query": ctx.query_for_retrieval})
            ctx.step_back_elapsed = time.time() - sb_start
            ctx.step_back_query = (sb_raw or "").strip().strip('"').strip()
            if ctx.step_back_output_max > 0 and len(ctx.step_back_query) > ctx.step_back_output_max:
                ctx.step_back_query = ctx.step_back_query[: ctx.step_back_output_max] + "..."
            if ctx.step_back_query and ctx.step_back_query != ctx.query_for_retrieval:
                ctx.step_back_parse_meta = {"ok": True, "method": "text", "error": None}
            else:
                ctx.step_back_query = ""
                ctx.step_back_parse_meta = {"ok": False, "method": "text", "error": "empty_or_duplicate"}
        except Exception as exc:  # noqa: BLE001
            _log_orchestrator_fallback("run_retrieval", exc)
            ctx.step_back_query = ""
            ctx.step_back_elapsed = 0.0
            ctx.step_back_parse_meta = {"ok": False, "method": None, "error": str(exc)[:200]}
    ctx.step_back_used = bool(ctx.step_back_query)
    return None


def _run_retrieval_decomposition_variants_phase(ctx: RetrievalRuntimeState) -> dict[str, Any] | None:
    ctx.decompose_elapsed = 0.0
    ctx.decompose_used = False
    ctx.decompose_model_used = None
    ctx.decompose_parse_meta: dict[str, Any] = {"ok": False, "method": None, "error": None}
    ctx.sub_questions: list[str] = []

    ctx.decompose_enabled = (
        bool(settings.ENABLE_QUERY_DECOMPOSITION)
        if ctx.state.get("enable_query_decomposition") is None
        else bool(ctx.state.get("enable_query_decomposition"))
    )
    decompose_result = _decompose_query(ctx.query_for_retrieval, ctx.engine, enabled=ctx.decompose_enabled)
    if isinstance(decompose_result, tuple) and len(decompose_result) == 4:
        ctx.sub_questions, ctx.decompose_elapsed, ctx.decompose_model_used, ctx.decompose_parse_meta = decompose_result
    elif isinstance(decompose_result, list):
        ctx.sub_questions = [str(item).strip() for item in decompose_result if str(item or "").strip()]
        if ctx.sub_questions:
            ctx.decompose_parse_meta = {"ok": True, "method": "patched", "error": None}

    ctx.decompose_used = bool(ctx.sub_questions)
    ctx.decompose_chain_enabled = bool(getattr(settings, "RAG_DECOMPOSITION_CHAIN_ENABLED", False))
    ctx.decompose_chain_requested = bool(ctx.decompose_chain_enabled and ctx.sub_questions)
    ctx.decompose_chain_used = False
    ctx.decompose_chain_steps = 0
    ctx.decompose_chain_elapsed = 0.0
    ctx.decompose_chain_queries: list[str] = []

    ctx.clause_fastlane_queries = build_clause_fastlane_queries(ctx.query_for_retrieval)
    if bool(getattr(settings, "RETRIEVAL_LIGHTWEIGHT_SUBQUERY_ENABLED", False)):
        ctx.lightweight_subqueries = build_lightweight_subquery_queries(
            ctx.query_for_retrieval,
            max_queries=int(getattr(settings, "RETRIEVAL_LIGHTWEIGHT_SUBQUERY_MAX_QUERIES", 3) or 3),
            min_query_chars=int(getattr(settings, "RETRIEVAL_LIGHTWEIGHT_SUBQUERY_MIN_QUERY_CHARS", 28) or 28),
        )
    else:
        ctx.lightweight_subqueries = []
    query_expansion_elapsed_ms = float(
        (
            ctx.alias_elapsed
            + ctx.dict_elapsed
            + ctx.kg_query_expansion_elapsed
            + ctx.multi_query_elapsed
            + ctx.step_back_elapsed
            + ctx.hyde_elapsed
            + ctx.decompose_elapsed
        )
        * 1000.0
    )
    query_variant_stage = build_query_variant_stage(
        QueryVariantStageInput(
            query_for_retrieval=ctx.query_for_retrieval,
            alias_queries=list(ctx.alias_queries or []),
            dict_expansions=list(ctx.dict_expansions or []),
            kg_query_expansion_queries=list(ctx.kg_query_expansion_queries or []),
            clause_fastlane_queries=list(ctx.clause_fastlane_queries or []),
            lightweight_subqueries=list(ctx.lightweight_subqueries or []),
            multi_queries=list(ctx.multi_queries or []),
            step_back_used=bool(ctx.step_back_used),
            step_back_query=str(ctx.step_back_query or ""),
            sub_questions=list(ctx.sub_questions or []),
            hyde_used=bool(ctx.hyde_used),
            hyde_text=str(ctx.hyde_text or ""),
            query_expansion_max_queries_raw=ctx.state.get("query_expansion_max_queries"),
            query_expansion_max_candidates_raw=ctx.state.get("query_expansion_max_candidates"),
            query_expansion_token_budget_raw=ctx.state.get("query_expansion_token_budget"),
            query_expansion_latency_budget_ms_raw=ctx.state.get("query_expansion_latency_budget_ms"),
            query_expansion_elapsed_ms=query_expansion_elapsed_ms,
        )
    )
    ctx.retrieval_queries = list(query_variant_stage.retrieval_queries or [])
    ctx.query_expansion_budget_meta = dict(query_variant_stage.query_expansion_budget_meta or {})
    ctx.query_expansion_budget_max_queries = int(query_variant_stage.query_expansion_budget_max_queries or 0)
    ctx.query_expansion_budget_max_candidates = int(query_variant_stage.query_expansion_budget_max_candidates or 0)
    ctx.query_expansion_budget_token_budget = int(query_variant_stage.query_expansion_budget_token_budget or 0)
    ctx.query_expansion_budget_latency_ms = float(query_variant_stage.query_expansion_budget_latency_ms or 0.0)
    return None


def _retriever_for_query_kind(ctx: RetrievalRuntimeState, kind: str) -> Any:
    if kind == "main":
        return ctx.retriever
    if kind == "hyde":
        return ctx.retriever.model_copy(
            update={"enable_reranker": False, "retrieval_mode": "vector", "enable_weight_rerank": False}
        )
    return ctx.retriever.model_copy(update={"enable_reranker": False})


def _hierarchy_invocation_debug(docs: list[Document], debug: dict[str, Any] | None) -> dict[str, Any]:
    family_keys: list[str] = []
    for doc in docs:
        metadata = doc.metadata or {}
        family_key = next(
            (
                str(metadata.get(key)).strip()
                for key in ("hierarchy_family_key", "parent_id", "parent_node_id")
                if metadata.get(key)
            ),
            "",
        )
        if family_key:
            family_keys.append(family_key)
    distinct_families = len(set(family_keys)) if family_keys else 0
    result = dict(debug or {})
    result["hierarchy_family"] = {
        "docs": len(docs),
        "docs_with_key": len(family_keys),
        "distinct_families": distinct_families,
        "duplicate_docs": max(0, len(family_keys) - distinct_families),
    }
    return result


def _invoke_retrieval_query(
    ctx: RetrievalRuntimeState,
    kind: str,
    query: str,
    retriever_obj: Any,
) -> tuple[str, list[Document], str | None, float, dict[str, Any] | None]:
    started = time.time()
    try:
        docs = DocUtilsMixin._annotate_docs_with_role(retriever_obj.invoke(query) or [], kind)
        debug = getattr(retriever_obj, "_last_debug_metrics", None)
        debug = _sanitize_retriever_debug(debug if isinstance(debug, dict) else None)
        if bool(ctx.hierarchy_recall_enabled) and docs:
            debug = _hierarchy_invocation_debug(docs, debug)
        return kind, docs, None, time.time() - started, debug
    except Exception as exc:  # noqa: BLE001
        _log_orchestrator_fallback("_invoke_with_timing", exc)
        return kind, [], str(exc)[:200], time.time() - started, None


def _record_retrieval_query(
    ctx: RetrievalRuntimeState,
    *,
    query: str,
    invocation: tuple[str, list[Document], str | None, float, dict[str, Any] | None],
) -> Any:
    kind, docs, error, elapsed, debug = invocation
    record = build_query_invocation_record(
        QueryInvocationRecordInput(
            kind=kind,
            query=query,
            docs=docs,
            error=error,
            elapsed_sec=elapsed,
            retriever_debug=debug,
        )
    )
    ctx.retrieval_per_query.append(record.per_query_item)
    if record.error_entry:
        ctx.retrieval_errors.append(record.error_entry)
    ctx.docs_by_query_kinds.append(record.kind)
    ctx.docs_by_query.append(record.docs)
    return record


def _summarize_decomposition_step(
    docs: list[Document],
    *,
    elapsed_sec: float,
    retrieval_mode: str,
    query: str,
    summarize: Any,
) -> str:
    try:
        citations = build_citations_from_docs(
            docs,
            retrieval_elapsed_sec=elapsed_sec,
            retrieval_mode=retrieval_mode,
            query=query,
        )
    except Exception as exc:
        _log_orchestrator_fallback("run_retrieval", exc)
        citations = []
    return summarize(citations)


def _run_decomposition_chain(ctx: RetrievalRuntimeState) -> None:
    if not ctx.decompose_chain_requested:
        return
    try:
        from app.rag.retrieval.decomposition_chain import build_chained_query, summarize_chain_step

        chain_started = time.time()
        prior_findings: list[str] = []
        retrieval_mode = str(ctx.retriever_update.get("retrieval_mode") or ctx.state.get("retrieval_mode") or "hybrid")
        for sub_question in ctx.sub_questions:
            chained_query = build_chained_query(sub_question, prior_findings)
            if not chained_query:
                continue
            ctx.decompose_chain_queries.append(chained_query)
            retriever_obj = ctx.retriever.model_copy(update={"enable_reranker": False})
            invocation = _invoke_retrieval_query(ctx, "subq", chained_query, retriever_obj)
            record = _record_retrieval_query(ctx, query=chained_query, invocation=invocation)
            summary = _summarize_decomposition_step(
                record.docs,
                elapsed_sec=float(invocation[3] or 0.0),
                retrieval_mode=retrieval_mode,
                query=chained_query,
                summarize=summarize_chain_step,
            )
            prior_findings.append(sub_question if not summary else f"{sub_question}: {summary}")
        ctx.decompose_chain_steps = len(ctx.decompose_chain_queries)
        ctx.decompose_chain_used = ctx.decompose_chain_steps > 0
        ctx.decompose_chain_elapsed = time.time() - chain_started
        if ctx.decompose_chain_used:
            ctx.retrieval_plan = [item for item in ctx.retrieval_plan if item[0] != "subq"]
    except Exception as exc:
        _log_orchestrator_fallback("run_retrieval", exc)
        ctx.decompose_chain_used = False
        ctx.decompose_chain_steps = 0
        ctx.decompose_chain_elapsed = 0.0
        ctx.decompose_chain_queries = []


def _run_retrieval_plan(ctx: RetrievalRuntimeState) -> None:
    if ctx.retrieval_parallelism <= 1 or len(ctx.retrieval_plan) <= 1:
        for kind, query, retriever_obj in ctx.retrieval_plan:
            invocation = _invoke_retrieval_query(ctx, kind, query, retriever_obj)
            _record_retrieval_query(ctx, query=query, invocation=invocation)
        return
    with concurrent.futures.ThreadPoolExecutor(max_workers=ctx.retrieval_parallelism) as pool:
        futures = [
            (query, pool.submit(_invoke_retrieval_query, ctx, kind, query, retriever_obj))
            for kind, query, retriever_obj in ctx.retrieval_plan
        ]
        for query, future in futures:
            _record_retrieval_query(ctx, query=query, invocation=future.result())


def _run_retrieval_retrieval_execution_phase(ctx: RetrievalRuntimeState) -> dict[str, Any] | None:
    ctx.docs_by_query = []
    ctx.docs_by_query_kinds = []
    ctx.retrieval_errors = []
    ctx.retrieval_per_query = []
    ctx.retrieval_parallelism = max(1, int(getattr(settings, "RETRIEVAL_QUERY_PARALLELISM", 1) or 1))
    ctx.retrieval_plan = [(kind, query, _retriever_for_query_kind(ctx, kind)) for kind, query in ctx.retrieval_queries]
    started = time.time()
    _run_decomposition_chain(ctx)
    _run_retrieval_plan(ctx)
    ctx.retrieval_elapsed = time.time() - started
    return None


def _hierarchy_family_features(ctx: RetrievalRuntimeState) -> tuple[bool, dict[str, dict[str, Any]]]:
    enabled = bool(ctx.hierarchy_recall_enabled and ctx.hierarchy_family_collapse and len(ctx.docs_by_query) > 1)
    if not enabled:
        return False, {}
    try:
        return True, _build_hierarchy_family_features(ctx.docs_by_query)
    except Exception as exc:
        _log_orchestrator_fallback("run_retrieval", exc)
        return True, {}


def _aggregate_hierarchy_families(
    docs: list[Document],
    *,
    enabled: bool,
    family_features: dict[str, dict[str, Any]],
    strategy: str,
) -> tuple[list[Document], dict[str, Any]]:
    if not enabled:
        return docs, {"enabled": False, "reason": "not_run"}
    try:
        return _apply_hierarchy_family_aggregation(
            docs,
            family_features=family_features,
            strategy=strategy,
        )
    except Exception as exc:
        _log_orchestrator_fallback("run_retrieval", exc)
        return docs, {"enabled": False, "reason": "exception"}


def _fuse_doc_lists(doc_lists: list[list[Document]]) -> list[Document]:
    if len(doc_lists) <= 1:
        return doc_lists[0] if doc_lists else []
    return DocUtilsMixin.fuse_docs_rrf(
        doc_lists,
        rrf_k=settings.RETRIEVAL_RRF_K,
        meta_prefix="query_expansion",
    )


def _append_unique_docs(
    target: list[Document],
    seen_keys: set[str],
    candidates: list[Document],
    *,
    limit: int,
) -> int:
    added = 0
    for doc in candidates:
        if len(target) >= limit:
            break
        key = DocUtilsMixin._doc_key(doc)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        target.append(doc)
        added += 1
    return added


def _aggregate_diversified_families(
    docs_non_mq: list[Document],
    docs_mq: list[Document],
    *,
    enabled: bool,
    family_features: dict[str, dict[str, Any]],
    strategy: str,
) -> tuple[list[Document], list[Document]]:
    if not enabled:
        return docs_non_mq, docs_mq
    try:
        docs_non_mq, _ = _apply_hierarchy_family_aggregation(
            docs_non_mq,
            family_features=family_features,
            strategy=strategy,
        )
        docs_mq, _ = _apply_hierarchy_family_aggregation(
            docs_mq,
            family_features=family_features,
            strategy=strategy,
        )
    except Exception as exc:
        logger.debug(_RETRIEVAL_ORCHESTRATOR_FALLBACK_LOG_MESSAGE, exc)
    return docs_non_mq, docs_mq


def _diversify_multi_query_docs(
    ctx: RetrievalRuntimeState,
    fused_docs: list[Document],
    *,
    family_aggregation_enabled: bool,
    family_features: dict[str, dict[str, Any]],
) -> list[Document]:
    mq_lists = [
        docs or [] for kind, docs in zip(ctx.docs_by_query_kinds, ctx.docs_by_query, strict=False) if kind == "mq"
    ]
    non_mq_lists = [
        docs or [] for kind, docs in zip(ctx.docs_by_query_kinds, ctx.docs_by_query, strict=False) if kind != "mq"
    ]
    if not mq_lists or not non_mq_lists:
        return fused_docs
    ctx.mq_diversify_used = True
    docs_non_mq = _fuse_doc_lists(non_mq_lists)
    docs_mq = _fuse_doc_lists(mq_lists)
    docs_non_mq, docs_mq = _aggregate_diversified_families(
        docs_non_mq,
        docs_mq,
        enabled=family_aggregation_enabled,
        family_features=family_features,
        strategy=ctx.hierarchy_family_aggregation,
    )
    selected: list[Document] = []
    selected_keys: set[str] = set()
    non_mq_limit = max(1, int(ctx.top_k) - int(ctx.mq_diversify_budget))
    ctx.mq_diversify_selected_non_mq = _append_unique_docs(
        selected,
        selected_keys,
        docs_non_mq,
        limit=non_mq_limit,
    )
    mq_limit = len(selected) + int(ctx.mq_diversify_budget)
    ctx.mq_diversify_selected_mq = _append_unique_docs(
        selected,
        selected_keys,
        docs_mq,
        limit=mq_limit,
    )
    ctx.mq_diversify_fill_from_fused = _append_unique_docs(
        selected,
        selected_keys,
        fused_docs,
        limit=int(ctx.top_k),
    )
    return selected


def _fuse_retrieval_docs(
    ctx: RetrievalRuntimeState,
    *,
    family_aggregation_enabled: bool,
    family_features: dict[str, dict[str, Any]],
) -> tuple[list[Document], list[Document]]:
    if len(ctx.docs_by_query) <= 1:
        docs = ctx.docs_by_query[0] if ctx.docs_by_query else []
        return docs, docs
    fused_docs = _fuse_doc_lists(ctx.docs_by_query)
    refill_pool = fused_docs
    fused_docs, ctx.family_aggregation_meta = _aggregate_hierarchy_families(
        fused_docs,
        enabled=family_aggregation_enabled,
        family_features=family_features,
        strategy=ctx.hierarchy_family_aggregation,
    )
    if ctx.mq_diversify_enabled and ctx.mq_diversify_budget > 0:
        fused_docs = _diversify_multi_query_docs(
            ctx,
            fused_docs,
            family_aggregation_enabled=family_aggregation_enabled,
            family_features=family_features,
        )
    return fused_docs, refill_pool


def _temporal_document_ids(docs: list[Document], *, limit: int) -> list[str]:
    document_ids: list[str] = []
    seen: set[str] = set()
    for doc in docs:
        metadata = doc.metadata if isinstance(doc.metadata, dict) else {}
        document_id = str(metadata.get("document_id") or "").strip()
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
    boost_enabled = bool(getattr(settings, "RAG_TEMPORAL_INTENT_RECENCY_BOOST_ENABLED", True))
    if not bool(ctx.temporal_intent_meta.get("detected")) or not boost_enabled:
        ctx.temporal_recency_meta = {"enabled": boost_enabled, "used": False, "reason": "not_detected"}
        return
    try:
        max_docs = max(0, int(getattr(settings, "RAG_TEMPORAL_INTENT_MAX_DOCS", 200) or 200))
        updated_ts = fetch_document_updated_ts(
            _temporal_document_ids(ctx.docs, limit=max_docs),
            tenant_id=ctx.state.get("tenant_id"),
            dataset_id=ctx.state.get("dataset_id"),
            max_docs=max_docs,
        )
        ctx.docs, ctx.temporal_recency_meta = apply_recency_boost(
            ctx.docs,
            updated_ts_by_document_id=updated_ts,
            boost_max=float(getattr(settings, "RETRIEVAL_GOVERNANCE_LATEST_BOOST_MAX", 0.0) or 0.0),
            window_days=int(getattr(settings, "RETRIEVAL_GOVERNANCE_LATEST_WINDOW_DAYS", 180) or 180),
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
            top_k=int(ctx.top_k),
            overfetch_factor=int(ctx.hierarchy_overfetch_factor),
        )
    except Exception as exc:
        _log_orchestrator_fallback("run_retrieval", exc)
        ctx.tree_dedup_meta = {"enabled": False, "reason": "exception"}


def _run_retrieval_fusion_phase(ctx: RetrievalRuntimeState) -> dict[str, Any] | None:
    ctx.top_k = int(
        ctx.retriever_update.get("k")
        or ctx.state.get("top_k", settings.RETRIEVAL_TOP_K)
        or settings.RETRIEVAL_TOP_K
        or 5
    )
    ctx.mq_diversify_enabled = bool(getattr(settings, "MULTI_QUERY_DIVERSIFY_ENABLED", False)) and bool(ctx.mq_enabled)
    try:
        mq_budget_raw = int(getattr(settings, "MULTI_QUERY_DIVERSIFY_BUDGET", 0) or 0)
    except (TypeError, ValueError, AttributeError):
        mq_budget_raw = 0
    ctx.mq_diversify_budget = max(0, min(int(mq_budget_raw or 0), int(ctx.top_k or 0)))
    ctx.mq_diversify_used = False
    ctx.mq_diversify_selected_mq = 0
    ctx.mq_diversify_selected_non_mq = 0
    ctx.mq_diversify_fill_from_fused = 0
    ctx.family_aggregation_meta: dict[str, Any] = {"enabled": False, "reason": "not_run"}
    ctx.tree_dedup_meta: dict[str, Any] = {"enabled": False, "reason": "not_run"}
    family_aggregation_enabled, family_features = _hierarchy_family_features(ctx)
    ctx.docs, docs_refill_pool = _fuse_retrieval_docs(
        ctx,
        family_aggregation_enabled=family_aggregation_enabled,
        family_features=family_features,
    )
    _apply_temporal_recency(ctx)
    _apply_hierarchy_tree_dedup_phase(ctx, docs_refill_pool)
    ctx.docs = (ctx.docs or [])[: max(0, ctx.top_k)]
    return None


def _kg_path_steps(raw_path: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_path, list):
        return []
    path: list[dict[str, Any]] = []
    for step in raw_path:
        if not isinstance(step, dict):
            continue
        entity_id = str(step.get("entity_id") or "").strip()
        if not entity_id:
            continue
        entry: dict[str, Any] = {"entity_id": entity_id}
        entity_type = str(step.get("type") or "").strip()
        if entity_type:
            entry["type"] = entity_type[:100]
        path.append(entry)
        if len(path) >= 6:
            break
    return path


def _kg_event_features(event: dict[str, Any]) -> dict[str, Any]:
    features = {
        key: event.get(key)
        for key in ("kg_path_length", "kg_shared_events", "kg_evidence_anchored")
        if event.get(key) is not None
    }
    path = _kg_path_steps(event.get("kg_path"))
    if path:
        features["kg_path"] = path
    provenance = _safe_kg_path_provenance(event.get("kg_path_provenance"))
    if provenance:
        features["kg_path_provenance"] = provenance
    return features


def _kg_event_candidate(event: Any) -> tuple[UUID, float, dict[str, Any]] | None:
    if not isinstance(event, dict) or event.get("chunk_id") is None:
        return None
    try:
        chunk_id = UUID(str(event.get("chunk_id")))
    except (TypeError, ValueError, AttributeError):
        return None
    try:
        score = float(event.get("score", 0.0) or 0.0)
    except (TypeError, ValueError, AttributeError):
        score = 0.0
    return chunk_id, score, _kg_event_features(event)


def _collect_kg_injection_candidates(
    events: Any,
    *,
    limit: int,
) -> tuple[list[UUID], dict[str, float], dict[str, dict[str, Any]]]:
    chunk_ids: list[UUID] = []
    scores: dict[str, float] = {}
    features: dict[str, dict[str, Any]] = {}
    seen: set[UUID] = set()
    for event in events if isinstance(events, list) else []:
        candidate = _kg_event_candidate(event)
        if candidate is None:
            continue
        chunk_id, score, chunk_features = candidate
        if chunk_id in seen:
            continue
        seen.add(chunk_id)
        chunk_ids.append(chunk_id)
        scores[str(chunk_id)] = score
        if chunk_features:
            features[str(chunk_id)] = chunk_features
        if len(chunk_ids) >= limit:
            break
    return chunk_ids, scores, features


def _fetch_kg_injection_rows(
    ctx: RetrievalRuntimeState,
    *,
    tenant_id: Any,
    account_id: Any,
    dataset_id: Any,
    dataset_ids: Any,
    document_ids: Any,
    chunk_ids: list[UUID],
) -> list[Any]:
    db = ctx.state.get("db")
    owns_db = False
    if db is None:
        try:
            from app.core.database import SessionLocal

            db = SessionLocal()
            owns_db = True
        except Exception as exc:
            _log_orchestrator_fallback("run_retrieval", exc)
            db = None
    try:
        fetch_kwargs = {
            "db": db,
            "tenant_id": tenant_id,
            "account_id": account_id,
            "dataset_id": dataset_id,
            "document_ids": document_ids,
            "chunk_ids": chunk_ids,
        }
        if dataset_ids:
            fetch_kwargs["dataset_ids"] = dataset_ids
        return list(_fetch_document_chunks_for_kg_injection(**fetch_kwargs) or [])
    finally:
        if owns_db and db is not None:
            try:
                db.close()
            except Exception as exc:
                logger.debug(_RETRIEVAL_ORCHESTRATOR_FALLBACK_LOG_MESSAGE, exc)


def _kg_chunk_row_map(rows: list[Any]) -> dict[UUID, Any]:
    chunks: dict[UUID, Any] = {}
    for chunk in rows:
        try:
            chunk_id = chunk.id
            content = chunk.content
        except (TypeError, ValueError, AttributeError):
            continue
        if chunk_id is not None and content is not None:
            chunks[chunk_id] = chunk
    return chunks


def _kg_document_from_chunk(
    chunk_id: UUID,
    chunk: Any,
    *,
    scores: dict[str, float],
    features: dict[str, dict[str, Any]],
) -> Document:
    metadata = dict(getattr(chunk, "doc_metadata", None) or {})
    metadata["retrieval_role"] = "kg"
    metadata.setdefault("document_id", str(getattr(chunk, "document_id", "") or ""))
    metadata.setdefault("chunk_id", str(getattr(chunk, "id", "") or ""))
    metadata.setdefault("chunk_index", getattr(chunk, "chunk_index", None))
    page_number = getattr(chunk, "page_number", None)
    if page_number is not None:
        metadata.setdefault("page", int(page_number))
        metadata.setdefault("page_number", int(page_number))
    start_char = getattr(chunk, "start_char", None)
    end_char = getattr(chunk, "end_char", None)
    if start_char is not None:
        metadata.setdefault("start_char", int(start_char))
    if end_char is not None:
        metadata.setdefault("end_char", int(end_char))
    score = scores.get(str(chunk_id))
    if score is not None:
        metadata.setdefault("retrieval_score", float(score or 0.0))
        metadata.setdefault("score", float(score or 0.0))
    for key, value in features.get(str(chunk_id), {}).items():
        if value is not None:
            metadata[key] = value
    return Document(
        page_content=str(getattr(chunk, "content", None) or ""),
        metadata=metadata,
        id=str(chunk_id),
    )


def _build_kg_injection_docs(
    chunk_ids: list[UUID],
    rows: list[Any],
    *,
    scores: dict[str, float],
    features: dict[str, dict[str, Any]],
) -> list[Document]:
    chunks = _kg_chunk_row_map(rows)
    return [
        _kg_document_from_chunk(chunk_id, chunks[chunk_id], scores=scores, features=features)
        for chunk_id in chunk_ids
        if chunk_id in chunks
    ]


def _run_kg_injection(ctx: RetrievalRuntimeState) -> list[Document]:
    tenant_id = ctx.state.get("tenant_id")
    account_id = ctx.state.get("account_id")
    document_ids, dataset_id, dataset_ids = _resolve_kg_scope(ctx.state)
    kg_result = ctx.kg_result_cached
    if kg_result is None:
        kg_kwargs = {
            "query": ctx.query_for_retrieval,
            "tenant_id": tenant_id,
            "document_ids": document_ids or None,
            "dataset_id": dataset_id,
            "account_id": account_id if not document_ids else None,
        }
        if dataset_ids:
            kg_kwargs["dataset_ids"] = dataset_ids
        kg_result = _run_kg_search_sync(kg_kwargs)
    chunk_ids, scores, features = _collect_kg_injection_candidates(
        (kg_result or {}).get("events") or [],
        limit=int(ctx.kg_chunk_injection_max_chunks or 0) or 5,
    )
    if not chunk_ids:
        return []
    rows = _fetch_kg_injection_rows(
        ctx,
        tenant_id=tenant_id,
        account_id=account_id,
        dataset_id=dataset_id,
        dataset_ids=dataset_ids,
        document_ids=document_ids,
        chunk_ids=chunk_ids,
    )
    return _build_kg_injection_docs(chunk_ids, rows, scores=scores, features=features)


def _run_retrieval_kg_injection_phase(ctx: RetrievalRuntimeState) -> dict[str, Any] | None:
    ctx.kg_chunk_injection_enabled = _coerce_optional_bool(
        ctx.state.get("enable_kg_chunk_injection"),
        default=bool(getattr(settings, "RAG_KG_CHUNK_INJECTION_ENABLED", False)),
    )
    ctx.kg_chunk_injection_max_chunks = _coerce_optional_int(
        ctx.state.get("kg_chunk_injection_max_chunks"),
        default=int(getattr(settings, "RAG_KG_CHUNK_INJECTION_MAX_CHUNKS", 5) or 5),
        minimum=0,
        maximum=50,
    )
    ctx.kg_chunks_injected = 0
    ctx.kg_chunk_injection_error: str | None = None
    try:
        enabled = (
            bool(ctx.kg_chunk_injection_enabled)
            and bool(getattr(settings, "KG_ENABLED", False))
            and bool(getattr(settings, "KG_CHAT_ENABLED", False))
            and ctx.state.get("tenant_id") is not None
            and any(_resolve_kg_scope(ctx.state))
        )
        if enabled:
            kg_docs = _run_kg_injection(ctx)
            if kg_docs:
                ctx.docs = _merge_kg_docs_preserving_main(ctx.docs, kg_docs)
                ctx.kg_chunks_injected = len(kg_docs)
    except Exception as exc:  # noqa: BLE001
        _log_orchestrator_fallback("run_retrieval", exc)
        ctx.kg_chunks_injected = 0
        ctx.kg_chunk_injection_error = str(exc)[:200]
    return None


def _tag_document(raw: Any) -> Document | None:
    if isinstance(raw, Document):
        return raw
    if not isinstance(raw, dict):
        return None
    content = raw.get("page_content")
    if content is None:
        content = raw.get("content")
    metadata = raw.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    try:
        return Document(
            page_content=str(content or ""),
            metadata=metadata,
            id=raw.get("id") or metadata.get("chunk_id"),
        )
    except Exception as exc:
        _log_orchestrator_fallback("run_retrieval", exc)
        return None


def _tag_documents(raw: Any) -> list[Document]:
    if not isinstance(raw, list):
        return []
    return [document for item in raw[:10] if (document := _tag_document(item)) is not None]


def _safe_metadata_float(metadata: dict[str, Any], key: str, *, fallback_key: str | None = None) -> float:
    raw = metadata.get(key)
    if raw is None and fallback_key is not None:
        raw = metadata.get(fallback_key)
    try:
        return float(raw or 0.0)
    except (TypeError, ValueError, AttributeError):
        return 0.0


def _safe_metadata_int(metadata: dict[str, Any], key: str, *, default: int) -> int:
    try:
        return int(metadata.get(key)) if metadata.get(key) is not None else default
    except (TypeError, ValueError, AttributeError):
        return default


def _kg_confidence_buckets(score: float) -> tuple[float, float, float]:
    if score >= 0.75:
        return 0.0, 0.0, 1.0
    if score >= 0.5:
        return 0.0, 1.0, 0.0
    if score > 0.0:
        return 1.0, 0.0, 0.0
    return 0.0, 0.0, 0.0


def _annotate_kg_ranking_features(doc: Document) -> None:
    metadata = doc.metadata or {}
    role = str(metadata.get("retrieval_role") or "main").strip().lower() or "main"
    has_kg_signal = _safe_metadata_float(metadata, "kg_pagerank") > 0.0
    if role != "kg" and not has_kg_signal:
        return
    kg_score = _safe_metadata_float(metadata, "kg_pagerank", fallback_key="score")
    metadata["kg_pagerank"] = kg_score
    metadata["kg_path_length"] = max(
        1,
        min(_safe_metadata_int(metadata, "kg_path_length", default=1), 5),
    )
    metadata["kg_shared_events"] = max(
        0,
        min(_safe_metadata_int(metadata, "kg_shared_events", default=1), 5),
    )
    metadata["kg_evidence_anchored"] = bool(metadata.get("kg_evidence_anchored", True))
    low, mid, high = _kg_confidence_buckets(kg_score)
    metadata["kg_edge_conf_low"] = low
    metadata["kg_edge_conf_mid"] = mid
    metadata["kg_edge_conf_high"] = high


def _annotate_kg_ranking_docs(docs: list[Document]) -> None:
    try:
        for doc in docs:
            if doc is not None:
                _annotate_kg_ranking_features(doc)
    except Exception as exc:
        logger.debug(_RETRIEVAL_ORCHESTRATOR_FALLBACK_LOG_MESSAGE, exc)


def _run_retrieval_tag_kg_boost_phase(ctx: RetrievalRuntimeState) -> dict[str, Any] | None:
    tag_docs = _tag_documents(ctx.state.get("tag_docs"))
    if tag_docs:
        ctx.docs = tag_docs + (ctx.docs or [])
    _annotate_kg_ranking_docs(ctx.docs or [])

    kg_chunk_boost_enabled = _coerce_optional_bool(
        ctx.state.get("enable_kg_chunk_boost"),
        default=bool(getattr(settings, "RAG_KG_CHUNK_BOOST_ENABLED", False)),
    )
    kg_chunk_boost_weight = _coerce_optional_float(
        ctx.state.get("kg_chunk_boost_weight"),
        default=float(getattr(settings, "RAG_KG_CHUNK_BOOST_WEIGHT", 0.25) or 0.25),
        minimum=0.0,
        maximum=1.0,
    )
    kg_chunk_boost_max_promoted = _coerce_optional_int(
        ctx.state.get("kg_chunk_boost_max_promoted"),
        default=int(getattr(settings, "RAG_KG_CHUNK_BOOST_MAX_PROMOTED", 3) or 3),
        minimum=0,
        maximum=20,
    )
    ctx.docs, ctx.kg_chunk_boost_meta = _apply_kg_chunk_boost(
        [d for d in (ctx.docs or []) if isinstance(d, Document)],
        enabled=bool(kg_chunk_boost_enabled),
        weight=float(kg_chunk_boost_weight),
        max_promoted=int(kg_chunk_boost_max_promoted),
    )
    return None


def _run_retrieval_post_rerank_hierarchy_setup_phase(ctx: RetrievalRuntimeState) -> dict[str, Any] | None:
    post_rerank_result = _run_post_rerank_stage(
        state=ctx.state,
        docs=[d for d in (ctx.docs or []) if isinstance(d, Document)],
        query_for_retrieval=ctx.query_for_retrieval,
        top_k=int(ctx.top_k),
    )
    ctx.docs = list(post_rerank_result.get("docs") or [])
    ctx.post_rerank_enabled = bool(post_rerank_result.get("post_rerank_enabled"))
    ctx.post_rerank_used = bool(post_rerank_result.get("post_rerank_used"))
    ctx.post_rerank_provider = post_rerank_result.get("post_rerank_provider")
    ctx.post_rerank_model_used = post_rerank_result.get("post_rerank_model_used")
    ctx.post_rerank_elapsed = float(post_rerank_result.get("post_rerank_elapsed") or 0.0)
    ctx.post_rerank_error = post_rerank_result.get("post_rerank_error")
    ctx.post_rerank_candidates_n = int(post_rerank_result.get("post_rerank_candidates_n") or 0)
    ctx.post_rerank_skip_reason = post_rerank_result.get("post_rerank_skip_reason")
    ctx.post_rerank_cache_enabled = bool(post_rerank_result.get("post_rerank_cache_enabled"))
    ctx.post_rerank_cache_backend = post_rerank_result.get("post_rerank_cache_backend")
    ctx.post_rerank_cache_hits = int(post_rerank_result.get("post_rerank_cache_hits") or 0)
    ctx.post_rerank_cache_misses = int(post_rerank_result.get("post_rerank_cache_misses") or 0)
    ctx.post_rerank_pipeline_enabled = bool(post_rerank_result.get("post_rerank_pipeline_enabled"))
    ctx.post_rerank_pipeline_used = bool(post_rerank_result.get("post_rerank_pipeline_used"))
    ctx.post_rerank_pipeline = list(post_rerank_result.get("post_rerank_pipeline") or [])
    ctx.post_rerank_pipeline_stages = list(post_rerank_result.get("post_rerank_pipeline_stages") or [])
    ctx.post_rerank_score_calibration_stats = dict(post_rerank_result.get("post_rerank_score_calibration_stats") or {})
    ctx.post_rerank_score_calibration_enabled = bool(ctx.post_rerank_score_calibration_stats.get("enabled"))
    ctx.post_rerank_score_calibration_alpha = float(ctx.post_rerank_score_calibration_stats.get("alpha") or 0.0)
    ctx.post_rerank_score_calibration_used = bool(ctx.post_rerank_score_calibration_stats.get("used"))

    hierarchy_expand_result = _run_hierarchy_expansion_stage(
        state=ctx.state,
        docs=[d for d in (ctx.docs or []) if isinstance(d, Document)],
        hierarchy_recall_enabled=bool(ctx.hierarchy_recall_enabled),
        hierarchy_parent_depth=int(ctx.hierarchy_parent_depth),
        hierarchy_sibling_window=int(ctx.hierarchy_sibling_window),
        top_k=int(ctx.top_k),
    )
    ctx.docs = list(hierarchy_expand_result.get("docs") or [])
    ctx.hierarchy_expand_attempted = bool(hierarchy_expand_result.get("hierarchy_expand_attempted"))
    ctx.hierarchy_expand_used = bool(hierarchy_expand_result.get("hierarchy_expand_used"))
    ctx.hierarchy_expand_error = hierarchy_expand_result.get("hierarchy_expand_error")
    ctx.hierarchy_expand_elapsed = float(hierarchy_expand_result.get("hierarchy_expand_elapsed") or 0.0)
    ctx.hierarchy_expand_meta = dict(hierarchy_expand_result.get("hierarchy_expand_meta") or {})
    ctx.retrieval_elapsed += float(ctx.hierarchy_expand_elapsed)

    ctx.hard_fallback_enabled = bool(ctx.retrieval_contract_policy.get("hard_fallback_enabled"))
    ctx.hard_fallback_mode = (
        str(ctx.retrieval_contract_policy.get("hard_fallback_mode") or "keyword").strip().lower() or "keyword"
    )
    ctx.hard_fallback_top_k = max(1, int(ctx.retrieval_contract_policy.get("hard_fallback_top_k") or 1))
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


def _contextual_evidence_gap(ctx: RetrievalRuntimeState, citations: list[dict[str, Any]]) -> dict[str, Any]:
    return detect_evidence_gap(
        citations=[citation for citation in citations if isinstance(citation, dict)],
        required_source_keys=(ctx.must_recall_expected_source_keys if ctx.must_recall_enabled else []),
        required_anchor_fields=(ctx.must_recall_required_anchor_fields if ctx.must_recall_enabled else []),
        min_citations=1,
    )


def _extend_unique(target: list[str], values: list[str], *, limit: int | None = None) -> None:
    for value in values:
        if value not in target:
            target.append(value)
            if limit is not None and len(target) >= limit:
                break


def _contextual_query_spec(
    ctx: RetrievalRuntimeState,
    spec: dict[str, Any],
    hop_diag: dict[str, Any],
) -> tuple[str, list[str]]:
    reason_codes = [str(value) for value in (spec.get("reason_codes") or []) if str(value).strip()][:8]
    hop_diag["reason_codes"] = reason_codes
    _extend_unique(ctx.contextual_followup_reason_codes, reason_codes)
    _extend_unique(ctx.iterative_pass_reason_codes, reason_codes)
    selected_terms = [str(value) for value in (spec.get("selected_terms") or []) if str(value).strip()]
    _extend_unique(ctx.contextual_followup_selected_terms, selected_terms, limit=10)
    query = str(spec.get("query") or "").strip()
    if query:
        ctx.contextual_followup_followup_query = query
        ctx.contextual_followup_query_hash = stable_hash(query)
        hop_diag["query_hash"] = ctx.contextual_followup_query_hash
    return query, reason_codes


def _invoke_contextual_followup(
    ctx: RetrievalRuntimeState,
    *,
    query: str,
    hop: int,
) -> list[Document]:
    started = time.time()
    docs: list[Document] = []
    error: str | None = None
    try:
        retriever_update = dict(ctx.retriever_update)
        retriever_update.update(
            {
                "retrieval_mode": str(ctx.contextual_followup_mode),
                "k": int(ctx.contextual_followup_top_k),
                "enable_reranker": False,
            }
        )
        retriever_obj = hybrid_retriever.model_copy(update=retriever_update)
        docs = DocUtilsMixin._annotate_docs_with_role(
            retriever_obj.invoke(query) or [],
            "contextual_followup",
        )
        debug = getattr(retriever_obj, "_last_debug_metrics", None)
        ctx.contextual_followup_retriever_debug = _sanitize_retriever_debug(debug if isinstance(debug, dict) else None)
    except Exception as exc:  # noqa: BLE001
        _log_orchestrator_fallback("run_retrieval", exc)
        error = str(exc)[:200]
    elapsed = max(0.0, float(time.time() - started))
    ctx.contextual_followup_elapsed += elapsed
    ctx.retrieval_elapsed += elapsed
    record = build_query_invocation_record(
        QueryInvocationRecordInput(
            kind="contextual_followup",
            query=query,
            docs=docs,
            error=error,
            elapsed_sec=elapsed,
            retriever_debug=ctx.contextual_followup_retriever_debug,
            hop=hop,
        )
    )
    ctx.retrieval_per_query.append(record.per_query_item)
    if record.error_entry:
        ctx.contextual_followup_error = error
        ctx.retrieval_errors.append(record.error_entry)
    return docs


def _safe_retrieval_doc_key(doc: Document) -> str | None:
    try:
        return _doc_key(doc)
    except Exception as exc:
        _log_orchestrator_fallback("run_retrieval", exc)
        return None


def _merge_contextual_docs(current: list[Document], incoming: list[Document]) -> tuple[list[Document], int]:
    merged = list(current)
    seen_keys = {key for doc in merged if doc is not None and (key := _safe_retrieval_doc_key(doc)) is not None}
    added = 0
    for doc in incoming:
        if doc is None:
            continue
        key = _safe_retrieval_doc_key(doc)
        if key and key in seen_keys:
            continue
        if key:
            seen_keys.add(key)
        merged.append(doc)
        added += 1
    return merged, added


def _apply_contextual_followup_docs(
    ctx: RetrievalRuntimeState,
    *,
    docs: list[Document],
    citations_before: list[dict[str, Any]],
    hop_diag: dict[str, Any],
    reason_codes: list[str],
) -> tuple[int, int]:
    if not docs:
        return 0, 0
    merged_docs, added_docs = _merge_contextual_docs(list(ctx.docs or []), docs)
    if added_docs <= 0:
        hop_diag["reason_codes"] = reason_codes + ["no_new_docs"]
        _extend_unique(ctx.iterative_pass_reason_codes, ["no_new_docs"])
        return 0, 0
    ctx.docs = merged_docs
    citations_after = build_citations_from_docs(
        ctx.docs,
        retrieval_elapsed_sec=ctx.retrieval_elapsed,
        retrieval_mode=ctx.request_retrieval_mode,
        query=ctx.query_for_retrieval,
    )
    added_citations = max(0, len(citations_after) - len(citations_before))
    ctx.contextual_followup_added_docs += added_docs
    ctx.contextual_followup_added_citations += added_citations
    ctx.contextual_followup_used = True
    ctx.iterative_pass_gap = _contextual_evidence_gap(ctx, citations_after)
    hop_diag["gap_after"] = dict(ctx.iterative_pass_gap or {})
    if not bool(ctx.iterative_pass_gap.get("has_gap")):
        _extend_unique(ctx.iterative_pass_reason_codes, ["gap_closed"])
    return added_docs, added_citations


def _run_contextual_followup_hop(ctx: RetrievalRuntimeState, hop: int) -> bool:
    citations_before = build_citations_from_docs(
        ctx.docs,
        retrieval_elapsed_sec=ctx.retrieval_elapsed,
        retrieval_mode=ctx.request_retrieval_mode,
        query=ctx.query_for_retrieval,
    )
    ctx.iterative_pass_gap = _contextual_evidence_gap(ctx, citations_before)
    hop_diag: dict[str, Any] = {
        "hop": hop,
        "attempted": False,
        "used": False,
        "query_hash": None,
        "added_docs": 0,
        "added_citations": 0,
        "reason_codes": [],
        "gap_before": dict(ctx.iterative_pass_gap or {}),
        "gap_after": None,
    }
    spec = build_contextual_followup_query(
        query=ctx.query_for_retrieval,
        docs=list(ctx.docs or []),
        evidence_gap=ctx.iterative_pass_gap,
        max_docs=int(ctx.contextual_followup_max_docs),
        max_terms=int(ctx.contextual_followup_max_terms),
        min_term_chars=int(ctx.contextual_followup_min_term_chars),
        max_query_chars=int(ctx.contextual_followup_max_query_chars),
    )
    if not isinstance(spec, dict):
        hop_diag["reason_codes"] = ["planner_spec_invalid"]
        ctx.iterative_pass_hops.append(hop_diag)
        ctx.iterative_pass_reason_codes.append("planner_spec_invalid")
        return False
    query, reason_codes = _contextual_query_spec(ctx, spec, hop_diag)
    if not (bool(spec.get("used")) and query):
        hop_diag["reason_codes"] = reason_codes or ["planner_not_used"]
        ctx.iterative_pass_hops.append(hop_diag)
        _extend_unique(ctx.iterative_pass_reason_codes, ["planner_not_used"])
        return False
    ctx.contextual_followup_attempted = True
    hop_diag["attempted"] = True
    docs = _invoke_contextual_followup(ctx, query=query, hop=hop)
    added_docs, added_citations = _apply_contextual_followup_docs(
        ctx,
        docs=docs,
        citations_before=citations_before,
        hop_diag=hop_diag,
        reason_codes=reason_codes,
    )
    hop_diag["used"] = added_docs > 0
    hop_diag["added_docs"] = added_docs
    hop_diag["added_citations"] = added_citations
    ctx.iterative_pass_hops.append(hop_diag)
    return bool(added_docs and (hop_diag.get("gap_after") or {}).get("has_gap"))


def _run_retrieval_contextual_followup_phase(ctx: RetrievalRuntimeState) -> dict[str, Any] | None:
    if not ctx.contextual_followup_enabled or not ctx.docs:
        return None
    iterative_start = time.time()
    for hop in range(1, int(ctx.contextual_followup_max_hops) + 1):
        elapsed_ms = (time.time() - iterative_start) * 1000.0
        if ctx.contextual_followup_latency_budget_ms > 0.0 and elapsed_ms >= ctx.contextual_followup_latency_budget_ms:
            ctx.iterative_pass_reason_codes.append("latency_budget_exhausted")
            break
        if not _run_contextual_followup_hop(ctx, hop):
            break
    return None


def _invoke_hard_fallback(ctx: RetrievalRuntimeState) -> list[Document]:
    started = time.time()
    docs: list[Document] = []
    error: str | None = None
    try:
        retriever_update = dict(ctx.retriever_update)
        retriever_update.update(
            {
                "retrieval_mode": ctx.hard_fallback_mode,
                "k": int(ctx.hard_fallback_top_k),
                "enable_reranker": False,
            }
        )
        retriever_obj = hybrid_retriever.model_copy(update=retriever_update)
        docs = DocUtilsMixin._annotate_docs_with_role(
            retriever_obj.invoke(ctx.query_for_retrieval) or [],
            "hard_fallback",
        )
        debug = getattr(retriever_obj, "_last_debug_metrics", None)
        ctx.hard_fallback_retriever_debug = _sanitize_retriever_debug(debug if isinstance(debug, dict) else None)
    except Exception as exc:  # noqa: BLE001
        _log_orchestrator_fallback("run_retrieval", exc)
        error = str(exc)[:200]
    ctx.hard_fallback_elapsed = max(0.0, float(time.time() - started))
    ctx.retrieval_elapsed += ctx.hard_fallback_elapsed
    record = build_query_invocation_record(
        QueryInvocationRecordInput(
            kind="hard_fallback",
            query=ctx.query_for_retrieval,
            docs=docs,
            error=error,
            elapsed_sec=ctx.hard_fallback_elapsed,
            retriever_debug=ctx.hard_fallback_retriever_debug,
        )
    )
    ctx.retrieval_per_query.append(record.per_query_item)
    if record.error_entry:
        ctx.hard_fallback_error = error
        ctx.retrieval_errors.append(record.error_entry)
    return docs


def _merge_hard_fallback_docs(
    current: list[Document],
    incoming: list[Document],
) -> tuple[list[Document], int]:
    merged: list[Document] = []
    seen_keys: set[str] = set()
    for doc in current:
        if doc is None:
            continue
        merged.append(doc)
        key = _safe_retrieval_doc_key(doc)
        if key:
            seen_keys.add(key)
    added = 0
    for doc in incoming:
        if doc is None:
            continue
        key = _safe_retrieval_doc_key(doc)
        if key and key in seen_keys:
            continue
        if key:
            seen_keys.add(key)
        merged.append(doc)
        added += 1
    return merged, added


def _run_hard_fallback(ctx: RetrievalRuntimeState) -> None:
    ctx.hard_fallback_attempted = True
    if ctx.retrieval_fallback_reason is None:
        ctx.retrieval_fallback_reason = "empty_retrieval"
    fallback_docs = _invoke_hard_fallback(ctx)
    if not fallback_docs:
        return
    ctx.docs, ctx.hard_fallback_added_docs = _merge_hard_fallback_docs(
        list(ctx.docs or []),
        fallback_docs,
    )
    citations_after = build_citations_from_docs(
        ctx.docs,
        retrieval_elapsed_sec=ctx.retrieval_elapsed,
        retrieval_mode=ctx.request_retrieval_mode,
        query=ctx.query_for_retrieval,
    )
    citations_after, missing_count = _filter_strict_span_citations(
        citations_after,
        enabled=bool(ctx.evidence_span_strict_enabled),
    )
    ctx.evidence_span_missing_citations += int(missing_count)
    ctx.hard_fallback_added_citations = max(0, len(citations_after) - len(ctx.citations))
    ctx.citations = citations_after
    ctx.hard_fallback_used = bool(ctx.hard_fallback_added_docs > 0 and ctx.citations)


def _run_retrieval_citations_hard_fallback_phase(ctx: RetrievalRuntimeState) -> dict[str, Any] | None:
    ctx.docs, ctx.metadata_exact_anchor_doc_order_meta = _apply_metadata_exact_anchor_doc_ordering(
        ctx.query_for_retrieval,
        [d for d in (ctx.docs or []) if isinstance(d, Document)],
    )

    ctx.evidence_span_strict_enabled = bool(ctx.retrieval_contract_policy.get("require_evidence_spans"))
    ctx.evidence_span_missing_citations = 0

    ctx.citations = build_citations_from_docs(
        ctx.docs,
        retrieval_elapsed_sec=ctx.retrieval_elapsed,
        retrieval_mode=ctx.request_retrieval_mode,
        query=ctx.query_for_retrieval,
    )
    ctx.citations, missing_count = _filter_strict_span_citations(
        ctx.citations,
        enabled=bool(ctx.evidence_span_strict_enabled),
    )
    ctx.evidence_span_missing_citations += int(missing_count)
    ctx.retrieval_fallback_reason: str | None = None
    if ctx.evidence_span_strict_enabled and not ctx.citations and ctx.evidence_span_missing_citations > 0:
        ctx.retrieval_fallback_reason = "strict_span_empty"

    if ctx.hard_fallback_enabled and not ctx.citations:
        _run_hard_fallback(ctx)
    return None


def _must_recall_doc_keys(docs: list[Document]) -> set[str]:
    keys: set[str] = set()
    for doc in docs:
        if doc is None:
            continue
        key = _safe_retrieval_doc_key(doc)
        if key:
            keys.add(key)
    return keys


def _invoke_must_recall_second_pass(ctx: RetrievalRuntimeState) -> list[Document]:
    try:
        retriever_update = dict(ctx.retriever_update)
        retriever_update.update(
            {
                "retrieval_mode": ctx.must_recall_second_pass_mode,
                "k": int(ctx.must_recall_second_pass_top_k),
                "enable_reranker": False,
            }
        )
        retriever_obj = hybrid_retriever.model_copy(update=retriever_update)
        return DocUtilsMixin._annotate_docs_with_role(
            retriever_obj.invoke(ctx.query_for_retrieval) or [],
            "must_recall_second_pass",
        )
    except Exception as exc:  # noqa: BLE001
        _log_orchestrator_fallback("run_retrieval", exc)
        ctx.must_recall_second_pass_error = str(exc)[:200]
        return []


def _merge_must_recall_second_pass_docs(
    current: list[Document],
    incoming: list[Document],
    *,
    seen_keys: set[str],
) -> tuple[list[Document], int]:
    merged = list(current)
    added = 0
    for doc in incoming:
        if doc is None:
            continue
        key = _safe_retrieval_doc_key(doc)
        if key and key in seen_keys:
            continue
        if key:
            seen_keys.add(key)
        merged.append(doc)
        added += 1
    return merged, added


def _must_recall_evaluations(ctx: RetrievalRuntimeState) -> tuple[dict[str, Any], dict[str, Any]]:
    citations = [citation for citation in ctx.citations if isinstance(citation, dict)]
    return (
        evaluate_required_source_keys(
            citations=citations,
            required_source_keys=ctx.must_recall_expected_source_keys,
        ),
        evaluate_evidence_anchor_expectations(
            citations=citations,
            required_fields=ctx.must_recall_required_anchor_fields,
            exclude_retrieval_role_prefixes=["hierarchy_"],
        ),
    )


def _run_must_recall_second_pass(
    ctx: RetrievalRuntimeState,
    *,
    source_eval: dict[str, Any],
    anchor_eval: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    ctx.must_recall_second_pass_attempted = True
    before_doc_keys = _must_recall_doc_keys(list(ctx.docs or []))
    citations_before = list(ctx.citations or [])
    fallback_docs = _invoke_must_recall_second_pass(ctx)
    if not fallback_docs:
        return source_eval, anchor_eval
    ctx.docs, ctx.must_recall_second_pass_added_docs = _merge_must_recall_second_pass_docs(
        list(ctx.docs or []),
        fallback_docs,
        seen_keys=before_doc_keys,
    )
    citations_after = build_citations_from_docs(
        ctx.docs,
        retrieval_elapsed_sec=ctx.retrieval_elapsed,
        retrieval_mode=ctx.request_retrieval_mode,
        query=ctx.query_for_retrieval,
    )
    ctx.citations, missing_count = _filter_strict_span_citations(
        citations_after,
        enabled=bool(ctx.evidence_span_strict_enabled),
    )
    ctx.evidence_span_missing_citations += int(missing_count)
    ctx.must_recall_second_pass_added_citations = max(0, len(ctx.citations) - len(citations_before))
    after_source_eval, after_anchor_eval = _must_recall_evaluations(ctx)
    after_missing_sources = list(after_source_eval.get("missing_source_keys") or [])
    after_anchor_missing = int(after_anchor_eval.get("missing_any") or 0)
    ctx.must_recall_second_pass_used = not after_missing_sources and after_anchor_missing <= 0
    ctx.must_recall_second_pass_diff = {
        "before_missing_source_keys": list(source_eval.get("missing_source_keys") or []),
        "after_missing_source_keys": after_missing_sources,
        "before_anchor_missing_any": int(anchor_eval.get("missing_any") or 0),
        "after_anchor_missing_any": after_anchor_missing,
        "before_citations": len(citations_before),
        "after_citations": len(ctx.citations),
        "added_docs": ctx.must_recall_second_pass_added_docs,
        "added_citations": ctx.must_recall_second_pass_added_citations,
    }
    return after_source_eval, after_anchor_eval


def _must_recall_status(ctx: RetrievalRuntimeState) -> str:
    if not ctx.must_recall_enabled:
        return "disabled"
    if ctx.must_recall_passed and ctx.must_recall_second_pass_attempted:
        return "partial_miss_recovered"
    if ctx.must_recall_passed:
        return "passed"
    return "failed"


def _run_retrieval_must_recall_phase(ctx: RetrievalRuntimeState) -> dict[str, Any] | None:
    must_recall_source_eval, ctx.must_recall_anchor_eval = _must_recall_evaluations(ctx)
    initial_missing_source_keys = list(must_recall_source_eval.get("missing_source_keys") or [])
    initial_anchor_missing_any = int(ctx.must_recall_anchor_eval.get("missing_any") or 0)
    partial_miss_detected = bool(
        ctx.must_recall_enabled and (bool(initial_missing_source_keys) or int(initial_anchor_missing_any or 0) > 0)
    )

    ctx.must_recall_second_pass_attempted = False
    ctx.must_recall_second_pass_used = False
    ctx.must_recall_second_pass_error: str | None = None
    ctx.must_recall_second_pass_added_docs = 0
    ctx.must_recall_second_pass_added_citations = 0
    ctx.must_recall_second_pass_diff: dict[str, Any] | None = None

    if partial_miss_detected and ctx.must_recall_second_pass_enabled:
        must_recall_source_eval, ctx.must_recall_anchor_eval = _run_must_recall_second_pass(
            ctx,
            source_eval=must_recall_source_eval,
            anchor_eval=ctx.must_recall_anchor_eval,
        )

    ctx.missing_source_keys = list(must_recall_source_eval.get("missing_source_keys") or [])
    anchor_missing_any = int(ctx.must_recall_anchor_eval.get("missing_any") or 0)
    ctx.must_recall_passed = bool(
        (not ctx.must_recall_enabled) or (not ctx.missing_source_keys and int(anchor_missing_any or 0) <= 0)
    )
    ctx.must_recall_fail_reasons = build_must_recall_fail_reasons(
        citations_count=len(ctx.citations or []),
        missing_source_keys=ctx.missing_source_keys,
        anchor_missing_any=anchor_missing_any,
        second_pass_attempted=ctx.must_recall_second_pass_attempted,
        second_pass_used=ctx.must_recall_second_pass_used,
    )
    ctx.must_recall_status = _must_recall_status(ctx)
    ctx.must_recall_second_pass_payload = {
        "enabled": bool(ctx.must_recall_second_pass_enabled),
        "attempted": bool(ctx.must_recall_second_pass_attempted),
        "used": bool(ctx.must_recall_second_pass_used),
        "mode": str(ctx.must_recall_second_pass_mode),
        "top_k": int(ctx.must_recall_second_pass_top_k),
        "added_docs": int(ctx.must_recall_second_pass_added_docs),
        "added_citations": int(ctx.must_recall_second_pass_added_citations),
        "error": ctx.must_recall_second_pass_error,
        "diff": (
            dict(ctx.must_recall_second_pass_diff) if isinstance(ctx.must_recall_second_pass_diff, dict) else None
        ),
    }
    ctx.must_recall_proof = build_must_recall_proof(
        enabled=bool(ctx.must_recall_enabled),
        status=str(ctx.must_recall_status),
        passed=bool(ctx.must_recall_passed),
        required_source_keys=ctx.must_recall_expected_source_keys,
        required_anchor_fields=ctx.must_recall_required_anchor_fields,
        source_eval=must_recall_source_eval,
        anchor_eval=ctx.must_recall_anchor_eval,
        fail_reasons=ctx.must_recall_fail_reasons,
        second_pass=ctx.must_recall_second_pass_payload,
        contract_fail_reason_taxonomy=str(
            ctx.retrieval_contract_policy.get("contract_fail_reason_taxonomy") or MUST_RECALL_FAIL_REASON_TAXONOMY_V1
        ),
    )

    ctx.coverage = _coverage_proxy_from_citations(ctx.citations)
    return None


def _run_retrieval_parse_quality_phase(ctx: RetrievalRuntimeState) -> dict[str, Any] | None:
    try:
        ctx.parse_quality_low_threshold = float(
            getattr(settings, "RETRIEVAL_PARSE_QUALITY_LOW_THRESHOLD", 0.35) or 0.35
        )
    except (TypeError, ValueError, AttributeError):
        ctx.parse_quality_low_threshold = 0.35
    ctx.parse_quality_low_threshold = min(1.0, max(0.0, float(ctx.parse_quality_low_threshold)))

    try:
        ctx.parse_quality_alert_ratio = float(getattr(settings, "RETRIEVAL_PARSE_QUALITY_ALERT_RATIO", 0.5) or 0.5)
    except (TypeError, ValueError, AttributeError):
        ctx.parse_quality_alert_ratio = 0.5
    ctx.parse_quality_alert_ratio = min(1.0, max(0.0, float(ctx.parse_quality_alert_ratio)))

    ctx.parse_quality_summary = _summarize_parse_quality_risk(
        ctx.docs,
        low_threshold=ctx.parse_quality_low_threshold,
        alert_ratio=ctx.parse_quality_alert_ratio,
    )
    ctx.parse_quality_gate_profile = (
        str(getattr(settings, "RETRIEVAL_PARSE_QUALITY_GATE_PROFILE", "warn") or "warn").strip().lower() or "warn"
    )
    if ctx.parse_quality_gate_profile not in {"off", "warn", "strict"}:
        ctx.parse_quality_gate_profile = "warn"
    ctx.parse_quality_gate_violation = bool((ctx.parse_quality_summary or {}).get("alert"))
    ctx.parse_quality_gate_blocked = bool(
        ctx.parse_quality_gate_profile == "strict" and ctx.parse_quality_gate_violation
    )
    ctx.parse_quality_gate_reason = "parse_quality_alert" if ctx.parse_quality_gate_violation else None
    try:
        parse_risk_hardcase_min_low_ratio = float(
            getattr(settings, "RETRIEVAL_PARSE_RISK_HARDCASE_MIN_LOW_RATIO", 0.5) or 0.5
        )
    except (TypeError, ValueError, AttributeError):
        parse_risk_hardcase_min_low_ratio = 0.5
    parse_risk_hardcase_min_low_ratio = min(1.0, max(0.0, float(parse_risk_hardcase_min_low_ratio)))

    try:
        parse_risk_hardcase_min_considered = int(
            getattr(settings, "RETRIEVAL_PARSE_RISK_HARDCASE_MIN_CONSIDERED", 3) or 3
        )
    except (TypeError, ValueError, AttributeError):
        parse_risk_hardcase_min_considered = 3
    parse_risk_hardcase_min_considered = max(1, int(parse_risk_hardcase_min_considered))

    ctx.parse_risk = _classify_parse_risk(
        summary=ctx.parse_quality_summary,
        hardcase_min_low_ratio=parse_risk_hardcase_min_low_ratio,
        hardcase_min_considered=parse_risk_hardcase_min_considered,
    )
    parse_repair_actions_input = ctx.state.get("parse_repair_actions")
    if parse_repair_actions_input is None:
        alt = ctx.state.get("parse_repair_schedule")
        if isinstance(alt, (dict, list)):
            parse_repair_actions_input = alt
    ctx.parse_repair_actions_meta = _sanitize_parse_repair_actions(parse_repair_actions_input)
    return None


def _run_retrieval_metrics_core_phase(ctx: RetrievalRuntimeState) -> dict[str, Any] | None:
    ctx.metrics = dict(ctx.state.get("metrics") or {})
    ctx.metrics["retrieval_elapsed_sec"] = round(ctx.retrieval_elapsed, 3)
    ctx.metrics["retrieval_mode"] = ctx.request_retrieval_mode
    ctx.metrics["retrieval_mode_requested"] = ctx.requested_retrieval_mode
    ctx.metrics["retrieval_mode_auto_routed"] = bool(ctx.retrieval_mode_routed)
    ctx.metrics["retrieval_profile"] = ctx.profile_norm or None
    ctx.metrics["retrieval_profile_requested"] = (
        str(ctx.requested_retrieval_profile).strip().lower() if ctx.requested_retrieval_profile is not None else None
    )
    ctx.metrics["temporal_intent_enabled"] = bool(ctx.temporal_intent_enabled)
    ctx.metrics["temporal_intent_detected"] = bool(ctx.temporal_intent_meta.get("detected"))
    ctx.metrics["temporal_intent_reason_codes"] = list(ctx.temporal_intent_meta.get("reason_codes") or [])
    ctx.metrics["temporal_recency_rerank"] = (
        dict(ctx.temporal_recency_meta) if isinstance(ctx.temporal_recency_meta, dict) else None
    )
    ctx.metrics["retrieval_contract_mode"] = ctx.retrieval_contract_mode or None
    ctx.metrics["retrieval_contract_policy"] = dict(ctx.retrieval_contract_policy or {})
    ctx.metrics["retrieval_contract_deterministic_recall"] = bool(ctx.contract_deterministic_recall)
    ctx.metrics["retrieval_contract_must_recall_strict"] = bool(ctx.contract_must_recall_strict)
    ctx.metrics["contract_fail_reason_taxonomy"] = str(
        ctx.retrieval_contract_policy.get("contract_fail_reason_taxonomy") or MUST_RECALL_FAIL_REASON_TAXONOMY_V1
    )
    ctx.metrics["must_recall_enabled"] = bool(ctx.must_recall_enabled)
    ctx.metrics["must_recall_requested"] = (
        bool(ctx.must_recall_requested) if ctx.must_recall_requested is not None else None
    )
    ctx.metrics["must_recall_expected_source_keys"] = list(ctx.must_recall_expected_source_keys or [])
    ctx.metrics["must_recall_required_anchor_fields"] = list(ctx.must_recall_required_anchor_fields or [])
    ctx.metrics["must_recall_auto_expected_source_keys_enabled"] = bool(
        ctx.must_recall_auto_expected_source_keys_enabled
    )
    ctx.metrics["must_recall_auto_expected_source_keys_applied"] = bool(
        ctx.must_recall_auto_expected_source_keys_applied
    )
    ctx.metrics["must_recall_auto_expected_source_keys"] = list(ctx.must_recall_auto_expected_source_keys or [])
    ctx.metrics["must_recall_auto_expected_source_keys_reason_codes"] = list(
        ctx.must_recall_auto_expected_source_keys_reason_codes or []
    )
    ctx.metrics["must_recall_auto_expected_source_keys_confidence"] = str(
        ctx.must_recall_auto_expected_source_keys_confidence or "none"
    )
    ctx.metrics["must_recall_auto_required_anchor_fields_enabled"] = bool(
        ctx.must_recall_auto_required_anchor_fields_enabled
    )
    ctx.metrics["must_recall_auto_required_anchor_fields_applied"] = bool(
        ctx.must_recall_auto_required_anchor_fields_applied
    )
    ctx.metrics["must_recall_auto_required_anchor_fields"] = list(ctx.must_recall_auto_required_anchor_fields or [])
    ctx.metrics["must_recall_auto_required_anchor_fields_reason_codes"] = list(
        ctx.must_recall_auto_required_anchor_fields_reason_codes or []
    )
    ctx.metrics["must_recall_status"] = str(ctx.must_recall_status)
    ctx.metrics["must_recall_passed"] = bool(ctx.must_recall_passed)
    ctx.metrics["must_recall_missing_source_keys"] = ctx.missing_source_keys[:40]
    ctx.metrics["must_recall_anchor_missing_counts"] = dict(ctx.must_recall_anchor_eval.get("missing_counts") or {})
    ctx.metrics["must_recall_anchor_considered_citations"] = int(
        ctx.must_recall_anchor_eval.get("considered_citations") or 0
    )
    ctx.metrics["must_recall_anchor_skipped_citations"] = int(ctx.must_recall_anchor_eval.get("skipped_citations") or 0)
    ctx.metrics["must_recall_anchor_skipped_by_role"] = dict(ctx.must_recall_anchor_eval.get("skipped_by_role") or {})
    ctx.metrics["must_recall_fail_reasons"] = ctx.must_recall_fail_reasons[:12]
    ctx.metrics["must_recall_second_pass_enabled"] = bool(ctx.must_recall_second_pass_enabled)
    ctx.metrics["must_recall_second_pass_attempted"] = bool(ctx.must_recall_second_pass_attempted)
    ctx.metrics["must_recall_second_pass_used"] = bool(ctx.must_recall_second_pass_used)
    ctx.metrics["must_recall_second_pass_mode"] = str(ctx.must_recall_second_pass_mode)
    ctx.metrics["must_recall_second_pass_top_k"] = int(ctx.must_recall_second_pass_top_k)
    ctx.metrics["must_recall_second_pass_added_docs"] = int(ctx.must_recall_second_pass_added_docs)
    ctx.metrics["must_recall_second_pass_added_citations"] = int(ctx.must_recall_second_pass_added_citations)
    ctx.metrics["must_recall_second_pass_error"] = ctx.must_recall_second_pass_error
    if isinstance(ctx.must_recall_second_pass_diff, dict):
        ctx.metrics["must_recall_second_pass_diff"] = dict(ctx.must_recall_second_pass_diff)
    ctx.metrics["must_recall_proof"] = dict(ctx.must_recall_proof)
    ctx.metrics["contextual_followup_enabled"] = bool(ctx.contextual_followup_enabled)
    ctx.metrics["contextual_followup_attempted"] = bool(ctx.contextual_followup_attempted)
    ctx.metrics["contextual_followup_used"] = bool(ctx.contextual_followup_used)
    ctx.metrics["contextual_followup_mode"] = str(ctx.contextual_followup_mode)
    ctx.metrics["contextual_followup_top_k"] = int(ctx.contextual_followup_top_k)
    ctx.metrics["contextual_followup_max_docs"] = int(ctx.contextual_followup_max_docs)
    ctx.metrics["contextual_followup_max_terms"] = int(ctx.contextual_followup_max_terms)
    ctx.metrics["contextual_followup_min_term_chars"] = int(ctx.contextual_followup_min_term_chars)
    ctx.metrics["contextual_followup_added_docs"] = int(ctx.contextual_followup_added_docs)
    ctx.metrics["contextual_followup_added_citations"] = int(ctx.contextual_followup_added_citations)
    ctx.metrics["contextual_followup_reason_codes"] = list(ctx.contextual_followup_reason_codes or [])
    ctx.metrics["contextual_followup_selected_terms"] = list(ctx.contextual_followup_selected_terms or [])
    ctx.metrics["contextual_followup_query_hash"] = ctx.contextual_followup_query_hash
    ctx.metrics["contextual_followup_elapsed_sec"] = round(float(ctx.contextual_followup_elapsed or 0.0), 3)
    ctx.metrics["contextual_followup_error"] = ctx.contextual_followup_error
    ctx.metrics["iterative_pass_enabled"] = bool(ctx.contextual_followup_enabled)
    ctx.metrics["iterative_pass_max_hops"] = int(ctx.contextual_followup_max_hops)
    ctx.metrics["iterative_pass_latency_budget_ms"] = round(float(ctx.contextual_followup_latency_budget_ms), 3)
    ctx.metrics["iterative_pass_hops_attempted"] = int(
        len([h for h in ctx.iterative_pass_hops if isinstance(h, dict) and bool(h.get("attempted"))])
    )
    ctx.metrics["iterative_pass_hops_used"] = int(
        len([h for h in ctx.iterative_pass_hops if isinstance(h, dict) and bool(h.get("used"))])
    )
    ctx.metrics["iterative_pass_reason_codes"] = list(ctx.iterative_pass_reason_codes or [])[:16]
    ctx.metrics["iterative_pass_gap"] = (
        dict(ctx.iterative_pass_gap or {}) if isinstance(ctx.iterative_pass_gap, dict) else None
    )
    ctx.metrics["iterative_pass_hops"] = [h for h in list(ctx.iterative_pass_hops or [])[:5] if isinstance(h, dict)]
    ctx.metrics["intent_router_enabled"] = bool(ctx.intent_router_meta.get("enabled"))
    ctx.metrics["intent_router_used"] = bool(ctx.intent_router_meta.get("used"))
    intent_router_learned_meta = (
        dict(ctx.intent_router_meta.get("learned_router") or {})
        if isinstance(ctx.intent_router_meta.get("learned_router"), dict)
        else None
    )
    ctx.metrics["intent_router_learned"] = intent_router_learned_meta
    ctx.metrics["intent_router_learned_used"] = bool((intent_router_learned_meta or {}).get("used"))
    ctx.metrics["intent_router_learned_confidence"] = float((intent_router_learned_meta or {}).get("confidence") or 0.0)
    ctx.metrics["intent_router_learned_confidence_gate"] = float(
        (intent_router_learned_meta or {}).get("confidence_gate") or 0.0
    )
    ctx.metrics["intent_router_learned_rule_id"] = (intent_router_learned_meta or {}).get("rule_id")
    ctx.metrics["intent_router"] = ctx.intent_router_meta
    ctx.metrics["industry_rules_enabled"] = bool(ctx.industry_rules_meta.get("enabled"))
    ctx.metrics["industry_rules_used"] = bool(ctx.industry_rules_meta.get("used"))
    ctx.metrics["industry_rules"] = ctx.industry_rules_meta
    ctx.metrics["adaptive_router_enabled"] = bool(ctx.adaptive_router_meta.get("enabled"))
    ctx.metrics["adaptive_router_used"] = bool(ctx.adaptive_router_meta.get("used"))
    ctx.metrics["adaptive_router"] = ctx.adaptive_router_meta
    ctx.metrics["channel_budget_policy_enabled"] = bool(ctx.channel_budget_policy_meta.get("enabled"))
    ctx.metrics["channel_budget_policy_used"] = bool(ctx.channel_budget_policy_meta.get("used"))
    ctx.metrics["channel_budget_policy"] = ctx.channel_budget_policy_meta
    ctx.metrics["retrieval_query_parallelism"] = ctx.retrieval_parallelism
    ctx.metrics["retrieval_query_count"] = len(ctx.retrieval_plan)
    ctx.metrics["retrieval_per_query"] = ctx.retrieval_per_query[:8]
    ctx.channel_health_queries: list[dict[str, Any]] = []
    ctx.retrieval_degraded_reason_codes: list[str] = []
    return None


def _retrieval_channel_health_item(item: Any) -> tuple[dict[str, Any] | None, list[str]]:
    if not isinstance(item, dict):
        return None, []
    debug = item.get("retriever_debug")
    debug = debug if isinstance(debug, dict) else {}
    channels = debug.get("channels")
    channels = channels if isinstance(channels, dict) else {}
    if not channels:
        return None, []
    degraded_reasons = list(channels.get("degraded_reasons") or [])
    health_item = {
        "kind": str(item.get("kind") or "main"),
        "attempted_channels": list(channels.get("attempted_channels") or []),
        "successful_channels": list(channels.get("successful_channels") or []),
        "retrieval_degraded": bool(channels.get("retrieval_degraded", False)),
        "degraded_reasons": degraded_reasons,
        "all_retrieval_channels_failed": bool(channels.get("all_retrieval_channels_failed", False)),
    }
    native_hybrid = channels.get("milvus_native_hybrid")
    if isinstance(native_hybrid, dict):
        health_item["milvus_native_hybrid"] = dict(native_hybrid)
    reason_codes = [
        f"{health_item['kind']}:{str(reason.get('channel') or '').strip() or 'unknown'}:"
        f"{str(reason.get('error_type') or '').strip() or 'unknown'}"
        for reason in degraded_reasons
        if isinstance(reason, dict)
    ]
    return health_item, reason_codes


def _run_retrieval_channel_health_phase(ctx: RetrievalRuntimeState) -> dict[str, Any] | None:
    for item in ctx.retrieval_per_query:
        health_item, reason_codes = _retrieval_channel_health_item(item)
        if health_item is None:
            continue
        ctx.channel_health_queries.append(health_item)
        ctx.retrieval_degraded_reason_codes.extend(reason_codes)
    channel_health_primary = next(
        (item for item in ctx.channel_health_queries if str(item.get("kind") or "") == "main"),
        (ctx.channel_health_queries[0] if ctx.channel_health_queries else None),
    )
    ctx.retrieval_channel_health = {
        "queries": ctx.channel_health_queries,
        "attempted_channels": list((channel_health_primary or {}).get("attempted_channels") or []),
        "successful_channels": list((channel_health_primary or {}).get("successful_channels") or []),
        "all_retrieval_channels_failed": bool(
            (channel_health_primary or {}).get("all_retrieval_channels_failed", False)
        ),
    }
    if isinstance((channel_health_primary or {}).get("milvus_native_hybrid"), dict):
        ctx.retrieval_channel_health["milvus_native_hybrid"] = dict(
            (channel_health_primary or {}).get("milvus_native_hybrid") or {}
        )
    ctx.retrieval_degraded = bool(any(bool(item.get("retrieval_degraded")) for item in ctx.channel_health_queries))
    ctx.retrieval_degraded_reason_codes = list(dict.fromkeys(ctx.retrieval_degraded_reason_codes))
    ctx.metrics["retrieval_degraded"] = bool(ctx.retrieval_degraded)
    ctx.metrics["retrieval_degraded_reasons"] = ctx.retrieval_degraded_reason_codes
    ctx.metrics["retrieval_channel_health"] = ctx.retrieval_channel_health
    ctx.metrics["retrieval_fallback_reason"] = ctx.retrieval_fallback_reason
    ctx.metrics["query_expansion_budget"] = dict(ctx.query_expansion_budget_meta)
    ctx.metrics["vector_backend"] = settings.VECTOR_BACKEND
    ctx.metrics["hard_fallback_enabled"] = bool(ctx.hard_fallback_enabled)
    ctx.metrics["hard_fallback_attempted"] = bool(ctx.hard_fallback_attempted)
    ctx.metrics["hard_fallback_used"] = bool(ctx.hard_fallback_used)
    ctx.metrics["hard_fallback_mode"] = ctx.hard_fallback_mode
    ctx.metrics["hard_fallback_top_k"] = int(ctx.hard_fallback_top_k)
    ctx.metrics["hard_fallback_elapsed_sec"] = round(float(ctx.hard_fallback_elapsed or 0.0), 3)
    ctx.metrics["hard_fallback_added_docs"] = int(ctx.hard_fallback_added_docs or 0)
    ctx.metrics["hard_fallback_added_citations"] = int(ctx.hard_fallback_added_citations or 0)
    ctx.metrics["hard_fallback_error"] = ctx.hard_fallback_error
    ctx.metrics["evidence_span_strict_enabled"] = bool(ctx.evidence_span_strict_enabled)
    ctx.metrics["evidence_span_missing_citations"] = int(ctx.evidence_span_missing_citations or 0)
    if ctx.coverage:
        ctx.metrics["citation_coverage"] = ctx.coverage
    if ctx.retrieval_errors:
        ctx.metrics["retrieval_errors"] = ctx.retrieval_errors[:5]
    ctx.empty_diag = _diagnose_empty_retrieval(ctx.metrics.get("retrieval_per_query")) if not ctx.citations else None
    if not ctx.citations and ctx.hard_fallback_attempted:
        ctx.empty_diag = dict(ctx.empty_diag or {})
        reasons = list(ctx.empty_diag.get("reasons") or [])
        if "hard_fallback_no_hit" not in reasons:
            reasons.append("hard_fallback_no_hit")
        ctx.empty_diag["reasons"] = reasons

        signals = dict(ctx.empty_diag.get("signals") or {})
        signals["hard_fallback_attempted"] = 1
        if ctx.hard_fallback_error:
            signals["hard_fallback_error"] = 1
        ctx.empty_diag["signals"] = signals

        ctx.empty_diag["hard_fallback"] = {
            "mode": ctx.hard_fallback_mode,
            "top_k": int(ctx.hard_fallback_top_k),
            "error": ctx.hard_fallback_error,
        }
    if ctx.empty_diag:
        ctx.metrics["empty_retrieval"] = ctx.empty_diag
    return None


def _run_retrieval_metrics_features_phase(ctx: RetrievalRuntimeState) -> dict[str, Any] | None:
    ctx.metrics["evidence_post_rerank_enabled"] = bool(ctx.post_rerank_enabled)
    ctx.metrics["evidence_post_rerank_used"] = bool(ctx.post_rerank_used)
    ctx.metrics["evidence_post_rerank_provider"] = ctx.post_rerank_provider
    ctx.metrics["evidence_post_rerank_candidates_n"] = int(ctx.post_rerank_candidates_n or 0)
    ctx.metrics["evidence_post_rerank_elapsed_sec"] = round(float(ctx.post_rerank_elapsed or 0.0), 3)
    ctx.metrics["evidence_post_rerank_model_used"] = ctx.post_rerank_model_used
    ctx.metrics["evidence_post_rerank_error"] = ctx.post_rerank_error
    ctx.metrics["evidence_post_rerank_skip_reason"] = ctx.post_rerank_skip_reason
    ctx.metrics["evidence_post_rerank_cache_enabled"] = bool(ctx.post_rerank_cache_enabled)
    ctx.metrics["evidence_post_rerank_cache_backend"] = ctx.post_rerank_cache_backend
    ctx.metrics["evidence_post_rerank_cache_hits"] = int(ctx.post_rerank_cache_hits or 0)
    ctx.metrics["evidence_post_rerank_cache_misses"] = int(ctx.post_rerank_cache_misses or 0)
    ctx.metrics["evidence_post_rerank_pipeline_enabled"] = bool(ctx.post_rerank_pipeline_enabled)
    ctx.metrics["evidence_post_rerank_pipeline_used"] = bool(ctx.post_rerank_pipeline_used)
    ctx.metrics["evidence_post_rerank_pipeline_stages"] = ctx.post_rerank_pipeline_stages[:4]
    ctx.metrics["evidence_post_rerank_score_calibration_enabled"] = bool(ctx.post_rerank_score_calibration_enabled)
    ctx.metrics["evidence_post_rerank_score_calibration_alpha"] = round(
        float(ctx.post_rerank_score_calibration_alpha), 4
    )
    ctx.metrics["evidence_post_rerank_score_calibration_used"] = bool(ctx.post_rerank_score_calibration_used)
    ctx.metrics["evidence_post_rerank_score_calibration"] = dict(ctx.post_rerank_score_calibration_stats or {})

    ctx.metrics["query_rewrite_enabled"] = bool(ctx.rewrite_enabled)
    ctx.metrics["query_rewrite_strategy_id"] = ctx.rewrite_strategy_id
    ctx.metrics["query_rewrite_strategy_hash"] = ctx.rewrite_strategy_hash
    ctx.metrics["rewrite_used"] = bool(ctx.rewrite_used)
    ctx.metrics["rewrite_elapsed_sec"] = round(ctx.rewrite_elapsed, 3)
    ctx.metrics["rewrite_model_used"] = ctx.rewrite_model_used

    ctx.metrics["alias_enabled"] = bool(ctx.alias_enabled)
    ctx.metrics["alias_used"] = bool(ctx.alias_used)
    ctx.metrics["alias_count"] = len(ctx.alias_queries)
    ctx.metrics["alias_elapsed_sec"] = round(ctx.alias_elapsed, 3)
    ctx.metrics["alias_meta"] = ctx.alias_meta

    ctx.metrics["dict_enabled"] = bool(ctx.dict_meta.get("enabled"))
    ctx.metrics["dict_used"] = bool(ctx.dict_used)
    ctx.metrics["dict_count"] = len(ctx.dict_expansions)
    ctx.metrics["dict_elapsed_sec"] = round(ctx.dict_elapsed, 3)
    ctx.metrics["dict_meta"] = ctx.dict_meta

    ctx.metrics["kg_query_expansion_enabled"] = bool(ctx.kg_query_expansion_enabled)
    ctx.metrics["kg_query_expansion_used"] = bool(ctx.kg_query_expansion_used)
    ctx.metrics["kg_query_expansion_entities_total"] = int(ctx.kg_query_expansion_entities_total)
    ctx.metrics["kg_query_expansion_entities_selected"] = int(ctx.kg_query_expansion_entities_selected)
    ctx.metrics["kg_query_expansion_query_count"] = int(len(ctx.kg_query_expansion_queries))
    ctx.metrics["kg_query_expansion_elapsed_sec"] = round(float(ctx.kg_query_expansion_elapsed), 3)
    ctx.metrics["kg_query_expansion_error"] = ctx.kg_query_expansion_error
    ctx.metrics["kg_chunk_injection_enabled"] = bool(ctx.kg_chunk_injection_enabled)
    ctx.metrics["kg_chunk_injection_max_chunks"] = int(ctx.kg_chunk_injection_max_chunks)
    ctx.metrics["kg_chunks_injected"] = int(ctx.kg_chunks_injected or 0)
    ctx.metrics["kg_chunk_injection_error"] = ctx.kg_chunk_injection_error
    ctx.metrics["kg_chunk_boost_enabled"] = bool(ctx.kg_chunk_boost_meta.get("enabled"))
    ctx.metrics["kg_chunk_boost_weight"] = float(ctx.kg_chunk_boost_meta.get("weight") or 0.0)
    ctx.metrics["kg_chunk_boost_max_promoted"] = int(ctx.kg_chunk_boost_meta.get("max_promoted") or 0)
    ctx.metrics["kg_chunk_boost_eligible"] = int(ctx.kg_chunk_boost_meta.get("eligible") or 0)
    ctx.metrics["kg_chunk_boost_promoted"] = int(ctx.kg_chunk_boost_meta.get("promoted") or 0)
    ctx.metrics["kg_chunk_boost_top_changed"] = bool(ctx.kg_chunk_boost_meta.get("top_changed"))
    ctx.metrics["kg_chunk_boost_reason"] = str(ctx.kg_chunk_boost_meta.get("reason") or "")
    ctx.metrics["metadata_exact_anchor_doc_ordering"] = dict(ctx.metadata_exact_anchor_doc_order_meta or {})

    ctx.metrics["multi_query_enabled"] = bool(ctx.mq_enabled)
    ctx.metrics["multi_query_used"] = bool(ctx.multi_query_used)
    ctx.metrics["multi_query_count"] = len(ctx.multi_queries)
    ctx.metrics["multi_query_elapsed_sec"] = round(ctx.multi_query_elapsed, 3)
    ctx.metrics["multi_query_model_used"] = ctx.multi_query_model_used
    ctx.metrics["multi_query_parse_ok"] = bool(ctx.multi_query_parse_meta.get("ok"))
    ctx.metrics["multi_query_parse_method"] = ctx.multi_query_parse_meta.get("method")
    ctx.metrics["multi_query_parse_error"] = ctx.multi_query_parse_meta.get("error")
    ctx.metrics["multi_query_diversify_enabled"] = bool(ctx.mq_diversify_enabled)
    ctx.metrics["multi_query_diversify_budget"] = int(ctx.mq_diversify_budget or 0) if ctx.mq_diversify_enabled else 0
    ctx.metrics["multi_query_diversify_used"] = bool(ctx.mq_diversify_used)
    ctx.metrics["multi_query_diversify_selected_mq"] = int(ctx.mq_diversify_selected_mq or 0)
    ctx.metrics["multi_query_diversify_selected_non_mq"] = int(ctx.mq_diversify_selected_non_mq or 0)
    ctx.metrics["multi_query_diversify_fill_from_fused"] = int(ctx.mq_diversify_fill_from_fused or 0)
    ctx.metrics["step_back_enabled"] = bool(ctx.step_back_enabled)
    ctx.metrics["step_back_used"] = bool(ctx.step_back_used)
    ctx.metrics["step_back_elapsed_sec"] = round(ctx.step_back_elapsed, 3)
    ctx.metrics["step_back_model_used"] = ctx.step_back_model_used
    ctx.metrics["step_back_parse_ok"] = bool(ctx.step_back_parse_meta.get("ok"))
    ctx.metrics["step_back_parse_method"] = ctx.step_back_parse_meta.get("method")
    ctx.metrics["step_back_parse_error"] = ctx.step_back_parse_meta.get("error")

    ctx.metrics["hierarchy_recall_enabled"] = bool(ctx.hierarchy_recall_enabled)
    ctx.metrics["hierarchy_family_collapse"] = bool(ctx.hierarchy_family_collapse)
    ctx.metrics["hierarchy_family_aggregation"] = str(ctx.hierarchy_family_aggregation)
    ctx.metrics["hierarchy_family_aggregation_meta"] = (
        dict(ctx.family_aggregation_meta) if isinstance(ctx.family_aggregation_meta, dict) else None
    )
    ctx.metrics["hierarchy_tree_dedup"] = bool(ctx.hierarchy_tree_dedup)
    ctx.metrics["hierarchy_tree_dedup_meta"] = (
        dict(ctx.tree_dedup_meta) if isinstance(ctx.tree_dedup_meta, dict) else None
    )
    ctx.metrics["hierarchy_parent_depth"] = int(ctx.hierarchy_parent_depth)
    ctx.metrics["hierarchy_sibling_window"] = int(ctx.hierarchy_sibling_window)
    ctx.metrics["hierarchy_overfetch_factor"] = int(ctx.hierarchy_overfetch_factor)
    ctx.metrics["hierarchy_context_expansion_attempted"] = bool(ctx.hierarchy_expand_attempted)
    ctx.metrics["hierarchy_context_expansion_used"] = bool(ctx.hierarchy_expand_used)
    ctx.metrics["hierarchy_context_expansion_elapsed_sec"] = round(float(ctx.hierarchy_expand_elapsed or 0.0), 3)
    ctx.metrics["hierarchy_context_expansion_error"] = ctx.hierarchy_expand_error
    ctx.metrics["hierarchy_context_expansion_meta"] = (
        dict(ctx.hierarchy_expand_meta) if isinstance(ctx.hierarchy_expand_meta, dict) else None
    )

    ctx.metrics["hyde_enabled"] = bool(ctx.hyde_enabled)
    ctx.metrics["hyde_used"] = bool(ctx.hyde_used)
    ctx.metrics["hyde_elapsed_sec"] = round(ctx.hyde_elapsed, 3)
    ctx.metrics["hyde_model_used"] = ctx.hyde_model_used

    ctx.metrics["decompose_enabled"] = bool(ctx.decompose_enabled)
    ctx.metrics["decompose_used"] = bool(ctx.decompose_used)
    ctx.metrics["decompose_count"] = len(ctx.sub_questions)
    ctx.metrics["decompose_elapsed_sec"] = round(ctx.decompose_elapsed, 3)
    ctx.metrics["decompose_model_used"] = ctx.decompose_model_used
    ctx.metrics["decompose_parse_ok"] = bool(ctx.decompose_parse_meta.get("ok"))
    ctx.metrics["decompose_parse_method"] = ctx.decompose_parse_meta.get("method")
    ctx.metrics["decompose_parse_error"] = ctx.decompose_parse_meta.get("error")
    ctx.metrics["decompose_chain_enabled"] = bool(ctx.decompose_chain_enabled)
    ctx.metrics["decompose_chain_used"] = bool(ctx.decompose_chain_used)
    ctx.metrics["decompose_chain_steps"] = int(ctx.decompose_chain_steps or 0)
    ctx.metrics["decompose_chain_elapsed_sec"] = round(float(ctx.decompose_chain_elapsed or 0.0), 3)
    ctx.metrics["parse_quality"] = dict(ctx.parse_quality_summary or {})
    ctx.metrics["parse_quality_low_threshold"] = float(ctx.parse_quality_low_threshold)
    ctx.metrics["parse_quality_alert_ratio"] = float(ctx.parse_quality_alert_ratio)
    ctx.metrics["parse_quality_alert"] = bool((ctx.parse_quality_summary or {}).get("alert"))
    ctx.metrics["parse_quality_low_ratio"] = float((ctx.parse_quality_summary or {}).get("low_ratio") or 0.0)
    ctx.metrics["parse_quality_considered"] = int((ctx.parse_quality_summary or {}).get("considered") or 0)
    ctx.metrics["parse_quality_recommendation"] = (ctx.parse_quality_summary or {}).get("recommendation")
    ctx.metrics["parse_quality_gate_profile"] = str(ctx.parse_quality_gate_profile)
    ctx.metrics["parse_quality_gate_violation"] = bool(ctx.parse_quality_gate_violation)
    ctx.metrics["parse_quality_gate_blocked"] = bool(ctx.parse_quality_gate_blocked)
    ctx.metrics["parse_quality_gate_reason"] = ctx.parse_quality_gate_reason
    ctx.metrics["parse_risk"] = dict(ctx.parse_risk or {})
    ctx.metrics["parse_risk_level"] = str(ctx.parse_risk.get("level") or "unknown")
    ctx.metrics["parse_risk_score"] = float(ctx.parse_risk.get("score") or 0.0)
    ctx.metrics["parse_risk_reason"] = str(ctx.parse_risk.get("reason") or "")
    ctx.metrics["parse_risk_hardcase_eligible"] = bool(ctx.parse_risk.get("hardcase_eligible"))
    ctx.metrics["parse_repair_actions"] = (
        dict(ctx.parse_repair_actions_meta) if isinstance(ctx.parse_repair_actions_meta, dict) else None
    )
    ctx.metrics["parse_repair_actions_enabled"] = bool(isinstance(ctx.parse_repair_actions_meta, dict))
    ctx.metrics["parse_repair_actions_run_id"] = (
        str(ctx.parse_repair_actions_meta.get("run_id") or "")
        if isinstance(ctx.parse_repair_actions_meta, dict)
        else ""
    ) or None
    return None


def _top_relevance_score(citations: list[dict[str, Any]]) -> float:
    if not citations:
        return 0.0
    try:
        return max(
            float(
                (
                    citation.get("relevance_score")
                    if citation.get("relevance_score") is not None
                    else citation.get("retrieval_score")
                )
                or 0.0
            )
            for citation in citations
        )
    except (TypeError, ValueError, AttributeError):
        return 0.0


def _apply_abstain_thresholds(ctx: RetrievalRuntimeState) -> None:
    if ctx.abstain_enabled:
        min_citations = max(0, int(settings.RAG_ABSTAIN_MIN_CITATIONS or 0))
        min_top_rel = float(settings.RAG_ABSTAIN_MIN_TOP_RELEVANCE_SCORE or 0.0)
        if min_citations > 0 and len(ctx.citations) < min_citations:
            ctx.abstain_triggered = True
            ctx.abstain_reason = "citations_lt_min"
        elif min_top_rel > 0 and ctx.top_rel < min_top_rel:
            ctx.abstain_triggered = True
            ctx.abstain_reason = "top_relevance_lt_min"
    if ctx.parse_quality_gate_blocked:
        ctx.abstain_enabled = True
        if not ctx.abstain_triggered:
            ctx.abstain_triggered = True
            ctx.abstain_reason = "parse_quality_gate_strict"
    if ctx.must_recall_enabled and not ctx.must_recall_passed:
        ctx.abstain_enabled = True
        if not ctx.abstain_triggered:
            ctx.abstain_triggered = True
            ctx.abstain_reason = "must_recall_failed"


def _apply_out_of_scope_guard(ctx: RetrievalRuntimeState) -> dict[str, Any]:
    result = maybe_apply_out_of_scope_live_guard(
        query=ctx.query_for_retrieval,
        enabled=bool(getattr(settings, "RAG_OUT_OF_SCOPE_LIVE_GUARD_ENABLED", False)),
        candidate=bool(ctx.abstain_triggered or not ctx.citations),
        current_triggered=bool(ctx.abstain_triggered),
        current_reason=ctx.abstain_reason,
        tenant_id=(str(ctx.state.get("tenant_id") or "").strip() or None),
        dataset_id=(str(ctx.state.get("dataset_id") or "").strip() or None),
        verifier=lambda: run_default_out_of_scope_live_guard(
            query=ctx.query_for_retrieval,
            tenant_id=str(ctx.state.get("tenant_id") or ""),
            dataset_id=str(ctx.state.get("dataset_id") or ""),
            ruleset_name=(str(getattr(settings, "RAG_OUT_OF_SCOPE_RULESET", "") or "").strip() or None),
            hyde_query=ctx.hyde_text if bool(ctx.hyde_used and ctx.hyde_text) else None,
            vector_similarity_threshold=float(getattr(settings, "RAG_OUT_OF_SCOPE_VECTOR_THRESHOLD", 0.35) or 0.35),
            hyde_similarity_threshold=float(getattr(settings, "RAG_OUT_OF_SCOPE_HYDE_THRESHOLD", 0.4) or 0.4),
        ),
    )
    ctx.abstain_triggered = bool(result.get("abstain_triggered"))
    ctx.abstain_reason = result.get("abstain_reason")
    return result


def _record_abstain_metrics(ctx: RetrievalRuntimeState, out_of_scope_guard: dict[str, Any]) -> None:
    ctx.metrics["abstain_enabled"] = bool(ctx.abstain_enabled)
    ctx.metrics["abstain_triggered"] = bool(ctx.abstain_triggered)
    ctx.metrics["abstain_reason"] = ctx.abstain_reason
    ctx.metrics["out_of_scope_guard_enabled"] = bool(getattr(settings, "RAG_OUT_OF_SCOPE_LIVE_GUARD_ENABLED", False))
    if isinstance(out_of_scope_guard.get("verdict"), dict):
        ctx.metrics["out_of_scope_guard"] = dict(out_of_scope_guard.get("verdict") or {})
    ctx.metrics["abstain_min_citations"] = int(settings.RAG_ABSTAIN_MIN_CITATIONS or 0)
    ctx.metrics["abstain_min_top_relevance_score"] = float(settings.RAG_ABSTAIN_MIN_TOP_RELEVANCE_SCORE or 0.0)
    ctx.metrics["visible_evidence_only_enabled"] = bool(ctx.strict_visible)
    ctx.metrics["visible_evidence_only_requested"] = bool(ctx.state.get("visible_evidence_only"))
    ctx.metrics["top_relevance_score"] = round(float(ctx.top_rel or 0.0), 3)
    if ctx.abstain_triggered:
        ctx.metrics["abstain_followup"] = build_abstain_followup(
            reason=ctx.abstain_reason,
            citations=ctx.citations,
        )


def _emit_retrieval_hardcase(ctx: RetrievalRuntimeState) -> None:
    enabled = bool(getattr(settings, "RETRIEVAL_HARDCASE_EMIT_ENABLED", False))
    if not enabled or (not ctx.abstain_triggered and ctx.citations):
        return
    reason = "abstain" if ctx.abstain_triggered else "no_citations"
    dedupe_payload = {
        "reason": reason,
        "query_hash": stable_hash(ctx.query_for_retrieval),
        "mode": str(ctx.request_retrieval_mode or ""),
        "profile": ctx.profile_norm or None,
        "cfg_hash": ctx.metrics.get("retrieval_config_hash"),
    }
    ctx.metrics["hardcase_candidate"] = {
        "schema": "mimirq.hardcase_candidate.v1",
        "reason": reason,
        "query_hash": stable_hash(ctx.query_for_retrieval),
        "retrieval_mode": str(ctx.request_retrieval_mode or ""),
        "retrieval_profile": ctx.profile_norm or None,
        "dedupe_key": stable_hash(
            json.dumps(dedupe_payload, ensure_ascii=False, sort_keys=True),
            length=32,
        ),
        "ts_ms": int(time.time() * 1000),
    }


def _parse_risk_enqueue_policy(ctx: RetrievalRuntimeState) -> dict[str, Any]:
    levels = {
        str(value).strip().lower()
        for value in parse_csv(
            str(getattr(settings, "RETRIEVAL_PARSE_RISK_AUTO_ENQUEUE_LEVELS", "high,medium") or "high,medium")
        )
        if str(value).strip()
    }
    if not levels:
        levels = {"high", "medium"}
    try:
        min_score = float(getattr(settings, "RETRIEVAL_PARSE_RISK_AUTO_ENQUEUE_MIN_SCORE", 0.0) or 0.0)
    except (TypeError, ValueError, AttributeError):
        min_score = 0.0
    return evaluate_parse_risk_auto_enqueue_policy(
        parse_risk=ctx.parse_risk,
        enabled=bool(getattr(settings, "RETRIEVAL_PARSE_RISK_HARDCASE_EMIT_ENABLED", False)),
        allowed_levels=levels,
        min_score=min(1.0, max(0.0, min_score)),
    )


def _emit_parse_risk_hardcase(ctx: RetrievalRuntimeState, policy: dict[str, Any]) -> None:
    if isinstance(ctx.metrics.get("hardcase_candidate"), dict) or not bool(policy.get("enqueue")):
        return
    candidate = build_parse_risk_hardcase_candidate(
        query_hash=stable_hash(ctx.query_for_retrieval),
        retrieval_mode=str(ctx.request_retrieval_mode or ""),
        retrieval_profile=(ctx.profile_norm or None),
        retrieval_config_hash=(ctx.metrics.get("retrieval_config_hash") if isinstance(ctx.metrics, dict) else None),
        parse_risk=ctx.parse_risk,
        ts_ms=int(time.time() * 1000),
    )
    if isinstance(candidate, dict):
        ctx.metrics["hardcase_candidate"] = candidate


def _run_retrieval_abstain_hardcase_phase(ctx: RetrievalRuntimeState) -> dict[str, Any] | None:
    ctx.strict_visible = bool(
        bool(ctx.state.get("visible_evidence_only"))
        or bool(ctx.retrieval_contract_policy.get("force_visible_evidence_only"))
    )
    ctx.abstain_enabled = (
        bool(settings.RAG_ABSTAIN_ENABLED) or ctx.strict_visible or bool(ctx.evidence_span_strict_enabled)
    )
    ctx.abstain_triggered = False
    ctx.abstain_reason: str | None = None
    ctx.top_rel = _top_relevance_score(ctx.citations)
    _apply_abstain_thresholds(ctx)
    out_of_scope_guard = _apply_out_of_scope_guard(ctx)
    _record_abstain_metrics(ctx, out_of_scope_guard)
    _emit_retrieval_hardcase(ctx)
    parse_risk_auto_enqueue_policy = _parse_risk_enqueue_policy(ctx)
    ctx.metrics["parse_risk_auto_enqueue_policy"] = dict(parse_risk_auto_enqueue_policy or {})
    _emit_parse_risk_hardcase(ctx, parse_risk_auto_enqueue_policy)
    return None


def _populate_query_normalization_debug(ctx: RetrievalRuntimeState) -> None:
    try:
        norm_text: str | None = None
        applied_rules: list[str] = []
        for item in ctx.retrieval_per_query:
            if item.get("kind") != "main":
                continue
            dbg = item.get("retriever_debug")
            dbg = dbg if isinstance(dbg, dict) else {}
            ch = dbg.get("channels")
            if isinstance(ch, dict):
                ctx.query_debug["channels"] = ch
            qn = dbg.get("query_normalization")
            qn = qn if isinstance(qn, dict) else {}
            norm_text = qn.get("normalized") if isinstance(qn.get("normalized"), str) else None
            ar = qn.get("applied_rules")
            if isinstance(ar, list):
                applied_rules = [str(x) for x in ar if x is not None]
            break
        if not norm_text:
            nq = normalize_query(ctx.query_for_retrieval)
            norm_text = nq.normalized_text
            applied_rules = list(nq.applied_rules or [])
        ctx.query_debug["normalized"] = norm_text
        ctx.query_debug["applied_rules"] = applied_rules[:20]
    except Exception as exc:
        _log_orchestrator_fallback("run_retrieval", exc)
        ctx.query_debug["normalized"] = ctx.query_for_retrieval
        ctx.query_debug["applied_rules"] = []


def _dictionary_debug_expansions(expansions: list[Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for expansion in expansions:
        if isinstance(expansion, dict):
            item = dict(expansion)
            item.setdefault("kind", "dict")
            result.append(item)
    return result


def _query_debug_expansions(ctx: RetrievalRuntimeState) -> list[dict[str, Any]]:
    expansions = [
        {"kind": "alias", "expanded_text": query, "source_rule_id": "alias", "weight": 1.0}
        for query in ctx.alias_queries
    ]
    expansions.extend(_dictionary_debug_expansions(ctx.dict_expansions))
    expansions.extend(
        {"kind": "kgq", "expanded_text": query, "source_rule_id": "kg:entity_name", "weight": 1.0}
        for query in ctx.kg_query_expansion_queries
    )
    expansions.extend(
        {"kind": "clause", "expanded_text": query, "source_rule_id": "policy:clause_ref", "weight": 1.0}
        for query in ctx.clause_fastlane_queries
    )
    expansions.extend(
        {"kind": "mq", "expanded_text": query, "source_rule_id": "llm:multi_query", "weight": 1.0}
        for query in ctx.multi_queries
    )
    if ctx.step_back_used and ctx.step_back_query:
        expansions.append(
            {
                "kind": "step_back",
                "expanded_text": ctx.step_back_query,
                "source_rule_id": "llm:step_back",
                "weight": 1.0,
            }
        )
    expansions.extend(
        {"kind": "subq", "expanded_text": query, "source_rule_id": "llm:decompose", "weight": 1.0}
        for query in ctx.sub_questions
    )
    if ctx.hyde_used and ctx.hyde_text:
        expansions.append({"kind": "hyde", "expanded_text": ctx.hyde_text, "source_rule_id": "llm:hyde", "weight": 1.0})
    return expansions[:20]


def _query_debug_contributions(ctx: RetrievalRuntimeState) -> list[dict[str, Any]]:
    try:
        by_role: dict[str, int] = {}
        for citation in ctx.citations:
            if not isinstance(citation, dict):
                continue
            role = str(citation.get("retrieval_role") or "main").strip() or "main"
            by_role[role] = by_role.get(role, 0) + 1
        return [
            {"retrieval_role": role, "citations": count}
            for role, count in sorted(by_role.items(), key=lambda item: (-item[1], item[0]))
        ]
    except Exception as exc:
        _log_orchestrator_fallback("run_retrieval", exc)
        return []


def _run_retrieval_query_debug_phase(ctx: RetrievalRuntimeState) -> dict[str, Any] | None:
    ctx.query_debug = {
        "original": ctx.question,
        "normalized": None,
        "applied_rules": [],
        "expansions": [],
        "contributions": [],
        "channels": None,
    }
    _populate_query_normalization_debug(ctx)
    ctx.query_debug["expansions"] = _query_debug_expansions(ctx)
    ctx.query_debug["decompose_chain"] = {
        "enabled": bool(ctx.decompose_chain_enabled),
        "used": bool(ctx.decompose_chain_used),
        "steps": int(ctx.decompose_chain_steps or 0),
        "queries": ctx.decompose_chain_queries[:5],
        "elapsed_sec": round(float(ctx.decompose_chain_elapsed or 0.0), 3),
    }
    if ctx.kg_query_expansion_entity_names:
        ctx.query_debug["kg_entities"] = ctx.kg_query_expansion_entity_names[:10]
    ctx.query_debug["contributions"] = _query_debug_contributions(ctx)

    ctx.query_debug["query_for_retrieval"] = ctx.query_for_retrieval
    ctx.query_debug["rewrite_used"] = bool(ctx.rewrite_used)
    ctx.query_debug["retrieval_profile"] = ctx.profile_norm or None
    ctx.query_debug["retrieval_profile_requested"] = (
        str(ctx.requested_retrieval_profile).strip().lower() if ctx.requested_retrieval_profile is not None else None
    )
    ctx.router_layers = build_router_layers(
        query=ctx.query_for_retrieval,
        entity_key=(str(ctx.state.get("entity_key") or "").strip() or None),
        partition_keys=(
            list(ctx.state.get("partition_keys") or []) if isinstance(ctx.state.get("partition_keys"), list) else None
        ),
        entity_candidates=(
            list(ctx.state.get("entity_candidates") or [])
            if isinstance(ctx.state.get("entity_candidates"), list)
            else None
        ),
        intent_meta=(ctx.intent_router_meta if isinstance(ctx.intent_router_meta, dict) else None),
    )
    ctx.query_debug["router_layers"] = ctx.router_layers
    ctx.query_debug["intent_router"] = ctx.intent_router_meta
    ctx.query_debug["industry_rules"] = ctx.industry_rules_meta
    ctx.query_debug["adaptive_router"] = ctx.adaptive_router_meta
    ctx.query_debug["channel_budget_policy"] = ctx.channel_budget_policy_meta
    ctx.query_debug["temporal_intent"] = {
        "enabled": bool(ctx.temporal_intent_enabled),
        "detected": bool(ctx.temporal_intent_meta.get("detected")),
        "reason_codes": list(ctx.temporal_intent_meta.get("reason_codes") or []),
        "recency_rerank": (dict(ctx.temporal_recency_meta) if isinstance(ctx.temporal_recency_meta, dict) else None),
    }
    ctx.query_debug["hierarchy_recall"] = {
        "enabled": bool(ctx.hierarchy_recall_enabled),
        "family_collapse": bool(ctx.hierarchy_family_collapse),
        "family_aggregation": str(ctx.hierarchy_family_aggregation),
        "family_aggregation_meta": (
            dict(ctx.family_aggregation_meta) if isinstance(ctx.family_aggregation_meta, dict) else None
        ),
        "tree_dedup": bool(ctx.hierarchy_tree_dedup),
        "parent_depth": int(ctx.hierarchy_parent_depth),
        "sibling_window": int(ctx.hierarchy_sibling_window),
        "overfetch_factor": int(ctx.hierarchy_overfetch_factor),
        "tree_dedup_meta": (dict(ctx.tree_dedup_meta) if isinstance(ctx.tree_dedup_meta, dict) else None),
        "context_expansion_attempted": bool(ctx.hierarchy_expand_attempted),
        "context_expansion_used": bool(ctx.hierarchy_expand_used),
        "context_expansion_elapsed_sec": round(float(ctx.hierarchy_expand_elapsed or 0.0), 3),
        "context_expansion_error": ctx.hierarchy_expand_error,
        "context_expansion_meta": (
            dict(ctx.hierarchy_expand_meta) if isinstance(ctx.hierarchy_expand_meta, dict) else None
        ),
    }
    ctx.query_debug["contextual_followup"] = {
        "enabled": bool(ctx.contextual_followup_enabled),
        "attempted": bool(ctx.contextual_followup_attempted),
        "used": bool(ctx.contextual_followup_used),
        "mode": str(ctx.contextual_followup_mode),
        "top_k": int(ctx.contextual_followup_top_k),
        "added_docs": int(ctx.contextual_followup_added_docs),
        "added_citations": int(ctx.contextual_followup_added_citations),
        "reason_codes": list(ctx.contextual_followup_reason_codes or []),
        "selected_terms": list(ctx.contextual_followup_selected_terms or []),
        "query": (
            str(ctx.contextual_followup_followup_query)[:220] if ctx.contextual_followup_followup_query else None
        ),
        "error": ctx.contextual_followup_error,
    }
    ctx.query_debug["iterative_pass"] = {
        "enabled": bool(ctx.contextual_followup_enabled),
        "max_hops": int(ctx.contextual_followup_max_hops),
        "latency_budget_ms": round(float(ctx.contextual_followup_latency_budget_ms), 3),
        "hops_attempted": int(
            len([h for h in ctx.iterative_pass_hops if isinstance(h, dict) and bool(h.get("attempted"))])
        ),
        "hops_used": int(len([h for h in ctx.iterative_pass_hops if isinstance(h, dict) and bool(h.get("used"))])),
        "reason_codes": list(ctx.iterative_pass_reason_codes or [])[:16],
        "gap": (dict(ctx.iterative_pass_gap or {}) if isinstance(ctx.iterative_pass_gap, dict) else None),
        "hops": [h for h in list(ctx.iterative_pass_hops or [])[:5] if isinstance(h, dict)],
    }
    ctx.query_debug["parse_quality"] = {
        "considered": int((ctx.parse_quality_summary or {}).get("considered") or 0),
        "low_ratio": float((ctx.parse_quality_summary or {}).get("low_ratio") or 0.0),
        "alert": bool((ctx.parse_quality_summary or {}).get("alert")),
        "recommendation": (ctx.parse_quality_summary or {}).get("recommendation"),
        "gate_profile": str(ctx.parse_quality_gate_profile),
        "gate_violation": bool(ctx.parse_quality_gate_violation),
        "gate_blocked": bool(ctx.parse_quality_gate_blocked),
        "gate_reason": ctx.parse_quality_gate_reason,
    }
    ctx.query_debug["parse_risk_auto_enqueue"] = (
        dict(ctx.metrics.get("parse_risk_auto_enqueue_policy"))
        if isinstance(ctx.metrics.get("parse_risk_auto_enqueue_policy"), dict)
        else None
    )
    ctx.query_debug["parse_repair_actions"] = (
        dict(ctx.metrics.get("parse_repair_actions"))
        if isinstance(ctx.metrics.get("parse_repair_actions"), dict)
        else None
    )
    ctx.query_debug["query_expansion_budget"] = dict(ctx.query_expansion_budget_meta)
    ctx.query_debug["retrieval_degraded"] = bool(ctx.retrieval_degraded)
    ctx.query_debug["retrieval_degraded_reasons"] = list(ctx.retrieval_degraded_reason_codes or [])
    ctx.query_debug["channel_health"] = dict(ctx.retrieval_channel_health)
    ctx.query_debug["fallback_reason"] = ctx.retrieval_fallback_reason
    ctx.query_debug["multi_query_ab"] = {
        "test_key": ctx.multi_query_ab_test_key,
        "variant": ctx.multi_query_ab_variant,
        "seed": ctx.multi_query_ab_seed,
        "forced_enable": bool(ctx.multi_query_ab_forced),
    }
    ctx.query_debug["retrieval_contract"] = {
        "mode": ctx.retrieval_contract_mode or None,
        "deterministic_recall": bool(ctx.contract_deterministic_recall),
        "must_recall_strict": bool(ctx.contract_must_recall_strict),
        "must_recall_enabled": bool(ctx.must_recall_enabled),
        "must_recall_status": str(ctx.must_recall_status),
        "must_recall_passed": bool(ctx.must_recall_passed),
        "must_recall_expected_source_keys": list(ctx.must_recall_expected_source_keys or []),
        "must_recall_missing_source_keys": list(ctx.missing_source_keys or [])[:20],
        "must_recall_required_anchor_fields": list(ctx.must_recall_required_anchor_fields or []),
        "must_recall_auto_expected_source_keys": {
            "enabled": bool(ctx.must_recall_auto_expected_source_keys_enabled),
            "applied": bool(ctx.must_recall_auto_expected_source_keys_applied),
            "keys": list(ctx.must_recall_auto_expected_source_keys or []),
            "reason_codes": list(ctx.must_recall_auto_expected_source_keys_reason_codes or []),
            "confidence": str(ctx.must_recall_auto_expected_source_keys_confidence or "none"),
        },
        "must_recall_auto_required_anchor_fields": {
            "enabled": bool(ctx.must_recall_auto_required_anchor_fields_enabled),
            "applied": bool(ctx.must_recall_auto_required_anchor_fields_applied),
            "fields": list(ctx.must_recall_auto_required_anchor_fields or []),
            "reason_codes": list(ctx.must_recall_auto_required_anchor_fields_reason_codes or []),
        },
        "must_recall_anchor_missing_counts": dict(ctx.must_recall_anchor_eval.get("missing_counts") or {}),
        "must_recall_fail_reasons": list(ctx.must_recall_fail_reasons or [])[:12],
        "contract_fail_reason_taxonomy": str(
            ctx.retrieval_contract_policy.get("contract_fail_reason_taxonomy") or MUST_RECALL_FAIL_REASON_TAXONOMY_V1
        ),
        "second_pass": dict(ctx.must_recall_second_pass_payload),
        "must_recall_proof": dict(ctx.must_recall_proof),
    }
    if ctx.empty_diag:
        ctx.query_debug["empty_retrieval"] = ctx.empty_diag
    return None


def _run_retrieval_retrieval_trace_phase(ctx: RetrievalRuntimeState) -> dict[str, Any] | None:
    ctx.retrieval_trace = build_retrieval_trace_stage(
        RetrievalTraceStageInput(
            query_for_retrieval=ctx.query_for_retrieval,
            requested_retrieval_mode=ctx.requested_retrieval_mode,
            request_retrieval_mode=ctx.request_retrieval_mode,
            retrieval_mode_routed=bool(ctx.retrieval_mode_routed),
            requested_retrieval_profile=ctx.requested_retrieval_profile,
            profile_norm=ctx.profile_norm or None,
            retrieval_contract_mode=ctx.retrieval_contract_mode or None,
            retrieval_contract_policy=dict(ctx.retrieval_contract_policy or {}),
            contract_deterministic_recall=bool(ctx.contract_deterministic_recall),
            must_recall_enabled=bool(ctx.must_recall_enabled),
            must_recall_status=str(ctx.must_recall_status),
            must_recall_passed=bool(ctx.must_recall_passed),
            must_recall_expected_source_keys=list(ctx.must_recall_expected_source_keys or []),
            missing_source_keys=list(ctx.missing_source_keys or []),
            must_recall_required_anchor_fields=list(ctx.must_recall_required_anchor_fields or []),
            must_recall_auto_expected_source_keys_enabled=bool(ctx.must_recall_auto_expected_source_keys_enabled),
            must_recall_auto_expected_source_keys_applied=bool(ctx.must_recall_auto_expected_source_keys_applied),
            must_recall_auto_expected_source_keys=list(ctx.must_recall_auto_expected_source_keys or []),
            must_recall_auto_expected_source_keys_reason_codes=list(
                ctx.must_recall_auto_expected_source_keys_reason_codes or []
            ),
            must_recall_auto_expected_source_keys_confidence=str(
                ctx.must_recall_auto_expected_source_keys_confidence or "none"
            ),
            must_recall_auto_required_anchor_fields_enabled=bool(ctx.must_recall_auto_required_anchor_fields_enabled),
            must_recall_auto_required_anchor_fields_applied=bool(ctx.must_recall_auto_required_anchor_fields_applied),
            must_recall_auto_required_anchor_fields=list(ctx.must_recall_auto_required_anchor_fields or []),
            must_recall_auto_required_anchor_fields_reason_codes=list(
                ctx.must_recall_auto_required_anchor_fields_reason_codes or []
            ),
            must_recall_anchor_eval=dict(ctx.must_recall_anchor_eval or {}),
            must_recall_fail_reasons=list(ctx.must_recall_fail_reasons or []),
            must_recall_second_pass_payload=dict(ctx.must_recall_second_pass_payload),
            must_recall_proof=dict(ctx.must_recall_proof),
            intent_router_meta=dict(ctx.intent_router_meta),
            industry_rules_meta=dict(ctx.industry_rules_meta),
            adaptive_router_meta=dict(ctx.adaptive_router_meta),
            channel_budget_policy_meta=dict(ctx.channel_budget_policy_meta),
            router_layers=dict(ctx.router_layers),
            contextual_followup_enabled=bool(ctx.contextual_followup_enabled),
            contextual_followup_attempted=bool(ctx.contextual_followup_attempted),
            contextual_followup_used=bool(ctx.contextual_followup_used),
            contextual_followup_mode=str(ctx.contextual_followup_mode),
            contextual_followup_top_k=int(ctx.contextual_followup_top_k),
            contextual_followup_max_docs=int(ctx.contextual_followup_max_docs),
            contextual_followup_max_terms=int(ctx.contextual_followup_max_terms),
            contextual_followup_min_term_chars=int(ctx.contextual_followup_min_term_chars),
            contextual_followup_query_hash=ctx.contextual_followup_query_hash,
            contextual_followup_added_docs=int(ctx.contextual_followup_added_docs),
            contextual_followup_added_citations=int(ctx.contextual_followup_added_citations),
            contextual_followup_reason_codes=list(ctx.contextual_followup_reason_codes or []),
            contextual_followup_selected_terms=list(ctx.contextual_followup_selected_terms or []),
            contextual_followup_elapsed=float(ctx.contextual_followup_elapsed or 0.0),
            contextual_followup_error=ctx.contextual_followup_error,
            contextual_followup_max_hops=int(ctx.contextual_followup_max_hops),
            contextual_followup_latency_budget_ms=float(ctx.contextual_followup_latency_budget_ms),
            iterative_pass_hops=list(ctx.iterative_pass_hops or []),
            iterative_pass_reason_codes=list(ctx.iterative_pass_reason_codes or []),
            iterative_pass_gap=(
                dict(ctx.iterative_pass_gap or {}) if isinstance(ctx.iterative_pass_gap, dict) else None
            ),
            hard_fallback_enabled=bool(ctx.hard_fallback_enabled),
            hard_fallback_attempted=bool(ctx.hard_fallback_attempted),
            hard_fallback_used=bool(ctx.hard_fallback_used),
            retrieval_fallback_reason=ctx.retrieval_fallback_reason,
            hard_fallback_mode=ctx.hard_fallback_mode,
            hard_fallback_top_k=int(ctx.hard_fallback_top_k),
            hard_fallback_elapsed=float(ctx.hard_fallback_elapsed or 0.0),
            hard_fallback_added_docs=int(ctx.hard_fallback_added_docs or 0),
            hard_fallback_added_citations=int(ctx.hard_fallback_added_citations or 0),
            hard_fallback_error=ctx.hard_fallback_error,
            rewrite_enabled=bool(ctx.rewrite_enabled),
            rewrite_strategy_id=ctx.rewrite_strategy_id,
            rewrite_strategy_hash=ctx.rewrite_strategy_hash,
            rewrite_temperature=ctx.rewrite_temperature,
            rewrite_max_chars=ctx.rewrite_max_chars,
            rewrite_used=bool(ctx.rewrite_used),
            rewrite_elapsed=float(ctx.rewrite_elapsed or 0.0),
            rewrite_model_used=ctx.rewrite_model_used,
            query_expansion_budget_meta=dict(ctx.query_expansion_budget_meta),
            alias_enabled=bool(ctx.alias_enabled),
            alias_used=bool(ctx.alias_used),
            alias_queries=list(ctx.alias_queries or []),
            alias_elapsed=float(ctx.alias_elapsed or 0.0),
            dict_meta=dict(ctx.dict_meta or {}),
            dict_used=bool(ctx.dict_used),
            dict_expansions=list(ctx.dict_expansions or []),
            dict_elapsed=float(ctx.dict_elapsed or 0.0),
            kg_query_expansion_enabled=bool(ctx.kg_query_expansion_enabled),
            kg_query_expansion_used=bool(ctx.kg_query_expansion_used),
            kg_query_expansion_entities_total=int(ctx.kg_query_expansion_entities_total),
            kg_query_expansion_entities_selected=int(ctx.kg_query_expansion_entities_selected),
            kg_query_expansion_queries=list(ctx.kg_query_expansion_queries or []),
            kg_query_expansion_elapsed=float(ctx.kg_query_expansion_elapsed or 0.0),
            kg_query_expansion_error=ctx.kg_query_expansion_error,
            clause_fastlane_queries=list(ctx.clause_fastlane_queries or []),
            lightweight_subqueries=list(ctx.lightweight_subqueries or []),
            mq_enabled=bool(ctx.mq_enabled),
            multi_query_used=bool(ctx.multi_query_used),
            multi_queries=list(ctx.multi_queries or []),
            multi_query_elapsed=float(ctx.multi_query_elapsed or 0.0),
            multi_query_model_used=ctx.multi_query_model_used,
            multi_query_parse_meta=dict(ctx.multi_query_parse_meta or {}),
            multi_query_ab_test_key=ctx.multi_query_ab_test_key,
            multi_query_ab_variant=ctx.multi_query_ab_variant,
            multi_query_ab_seed=ctx.multi_query_ab_seed,
            multi_query_ab_forced=bool(ctx.multi_query_ab_forced),
            step_back_enabled=bool(ctx.step_back_enabled),
            step_back_used=bool(ctx.step_back_used),
            step_back_elapsed=float(ctx.step_back_elapsed or 0.0),
            step_back_model_used=ctx.step_back_model_used,
            step_back_parse_meta=dict(ctx.step_back_parse_meta or {}),
            hyde_enabled=bool(ctx.hyde_enabled),
            hyde_used=bool(ctx.hyde_used),
            hyde_elapsed=float(ctx.hyde_elapsed or 0.0),
            hyde_model_used=ctx.hyde_model_used,
            decompose_used=bool(ctx.decompose_used),
            sub_questions=list(ctx.sub_questions or []),
            decompose_elapsed=float(ctx.decompose_elapsed or 0.0),
            decompose_model_used=ctx.decompose_model_used,
            decompose_parse_meta=dict(ctx.decompose_parse_meta or {}),
            top_k=int(ctx.top_k),
            retriever_update=dict(ctx.retriever_update or {}),
            retrieval_parallelism=int(ctx.retrieval_parallelism),
            retrieval_plan=list(ctx.retrieval_plan or []),
            retrieval_per_query=list(ctx.retrieval_per_query or []),
            retrieval_errors=list(ctx.retrieval_errors or []),
            retrieval_elapsed=float(ctx.retrieval_elapsed or 0.0),
            retrieval_degraded=bool(ctx.retrieval_degraded),
            retrieval_degraded_reason_codes=list(ctx.retrieval_degraded_reason_codes or []),
            retrieval_channel_health=dict(ctx.retrieval_channel_health),
            docs_by_query=ctx.docs_by_query,
            mq_diversify_enabled=bool(ctx.mq_diversify_enabled),
            mq_diversify_budget=int(ctx.mq_diversify_budget or 0),
            mq_diversify_used=bool(ctx.mq_diversify_used),
            mq_diversify_selected_mq=int(ctx.mq_diversify_selected_mq or 0),
            mq_diversify_selected_non_mq=int(ctx.mq_diversify_selected_non_mq or 0),
            mq_diversify_fill_from_fused=int(ctx.mq_diversify_fill_from_fused or 0),
            hierarchy_recall_enabled=bool(ctx.hierarchy_recall_enabled),
            hierarchy_family_collapse=bool(ctx.hierarchy_family_collapse),
            hierarchy_family_aggregation=str(ctx.hierarchy_family_aggregation),
            hierarchy_tree_dedup=bool(ctx.hierarchy_tree_dedup),
            hierarchy_parent_depth=int(ctx.hierarchy_parent_depth),
            hierarchy_sibling_window=int(ctx.hierarchy_sibling_window),
            hierarchy_overfetch_factor=int(ctx.hierarchy_overfetch_factor),
            kg_chunk_injection_enabled=bool(ctx.kg_chunk_injection_enabled),
            kg_chunk_injection_max_chunks=int(ctx.kg_chunk_injection_max_chunks),
            kg_chunks_injected=int(ctx.kg_chunks_injected or 0),
            kg_chunk_boost_meta=dict(ctx.kg_chunk_boost_meta or {}),
            kg_chunk_injection_error=ctx.kg_chunk_injection_error,
            post_rerank_enabled=bool(ctx.post_rerank_enabled),
            post_rerank_used=bool(ctx.post_rerank_used),
            post_rerank_provider=ctx.post_rerank_provider,
            post_rerank_skip_reason=ctx.post_rerank_skip_reason,
            post_rerank_cache_enabled=bool(ctx.post_rerank_cache_enabled),
            post_rerank_cache_backend=ctx.post_rerank_cache_backend,
            post_rerank_cache_hits=int(ctx.post_rerank_cache_hits or 0),
            post_rerank_cache_misses=int(ctx.post_rerank_cache_misses or 0),
            post_rerank_pipeline_enabled=bool(ctx.post_rerank_pipeline_enabled),
            post_rerank_pipeline_used=bool(ctx.post_rerank_pipeline_used),
            post_rerank_pipeline=list(ctx.post_rerank_pipeline or []),
            post_rerank_pipeline_stages=list(ctx.post_rerank_pipeline_stages or []),
            post_rerank_candidates_n=int(ctx.post_rerank_candidates_n or 0),
            post_rerank_elapsed=float(ctx.post_rerank_elapsed or 0.0),
            post_rerank_model_used=ctx.post_rerank_model_used,
            post_rerank_score_calibration_stats=dict(ctx.post_rerank_score_calibration_stats or {}),
            post_rerank_error=ctx.post_rerank_error,
            abstain_enabled=bool(ctx.abstain_enabled),
            abstain_triggered=bool(ctx.abstain_triggered),
            abstain_reason=ctx.abstain_reason,
            evidence_span_strict_enabled=bool(ctx.evidence_span_strict_enabled),
            evidence_span_missing_citations=int(ctx.evidence_span_missing_citations or 0),
            top_rel=float(ctx.top_rel or 0.0),
            citations=[citation for citation in ctx.citations if isinstance(citation, dict)],
            docs=list(ctx.docs or []),
            parse_quality_summary=dict(ctx.parse_quality_summary or {}),
            parse_quality_gate_profile=str(ctx.parse_quality_gate_profile),
            parse_quality_gate_violation=bool(ctx.parse_quality_gate_violation),
            parse_quality_gate_blocked=bool(ctx.parse_quality_gate_blocked),
            parse_quality_gate_reason=ctx.parse_quality_gate_reason,
            parse_risk=dict(ctx.parse_risk or {}),
            metrics=dict(ctx.metrics or {}),
        )
    ).retrieval_trace
    observe_router_layers(ctx.router_layers)
    return None


def _run_retrieval_config_and_result_phase(ctx: RetrievalRuntimeState) -> dict[str, Any] | None:
    try:
        retrieval_cfg: dict[str, Any] = {
            "requested_retrieval_mode": str(ctx.requested_retrieval_mode or ""),
            "retrieval_mode": str(ctx.request_retrieval_mode or ""),
            "retrieval_mode_auto_routed": bool(ctx.retrieval_mode_routed),
            "retrieval_profile": ctx.profile_norm or None,
            "top_k": int(ctx.top_k),
            "score_threshold": float(ctx.retriever_update.get("score_threshold") or 0.0),
            "alpha": float(ctx.retriever_update.get("alpha") or 0.0),
            "fusion_strategy": str(ctx.retriever_update.get("fusion_strategy") or "linear"),
            "fusion_budgets": (
                ctx.retriever_update.get("fusion_budgets")
                if isinstance(ctx.retriever_update.get("fusion_budgets"), dict)
                else None
            ),
            "fusion_min_scores": (
                ctx.retriever_update.get("fusion_min_scores")
                if isinstance(ctx.retriever_update.get("fusion_min_scores"), dict)
                else None
            ),
            "fusion_weights": (
                ctx.retriever_update.get("fusion_weights")
                if isinstance(ctx.retriever_update.get("fusion_weights"), dict)
                else None
            ),
            "enable_weight_rerank": bool(ctx.retriever_update.get("enable_weight_rerank", True)),
            "vector_weight": float(ctx.retriever_update.get("vector_weight") or 0.0),
            "keyword_weight": float(ctx.retriever_update.get("keyword_weight") or 0.0),
            "mmr_lambda": float(ctx.retriever_update.get("mmr_lambda") or 0.0),
            "enable_reranker": bool(ctx.retriever_update.get("enable_reranker", False)),
            "reranker_provider": str(ctx.retriever_update.get("reranker_provider") or ""),
            "reranker_tier": describe_reranker_provider(
                str(ctx.retriever_update.get("reranker_provider") or ""),
                provider_name=str(getattr(settings, "COLBERT_RERANK_PROVIDER", "deterministic") or "deterministic"),
            ).get("tier"),
            "reranker_top_n": int(ctx.retriever_update.get("reranker_top_n") or 0),
            "visible_evidence_only": bool(ctx.strict_visible),
            # Global retrieval channel toggles (low-cardinality).
            "vector_backend": str(getattr(settings, "VECTOR_BACKEND", "") or ""),
            "bm25_enabled": bool(getattr(settings, "BM25_INDEX_ENABLED", False)),
            "lexical_enabled": bool(getattr(settings, "LEXICAL_DB_TRGM_ENABLED", False)),
            "sparse_enabled": bool(ctx.sparse_enabled),
            "sparse_provider": ctx.sparse_provider,
            "sparse_index_persist_enabled": bool(getattr(settings, "SPARSE_RETRIEVAL_INDEX_PERSIST_ENABLED", False)),
            "colbert_enabled": bool(getattr(settings, "COLBERT_RETRIEVAL_ENABLED", False)),
            "colbert_provider": str(getattr(settings, "COLBERT_RETRIEVAL_PROVIDER", "") or ""),
            "colbert_index_persist_enabled": bool(getattr(settings, "COLBERT_RETRIEVAL_INDEX_PERSIST_ENABLED", False)),
            "colbert_max_docs": int(getattr(settings, "COLBERT_RETRIEVAL_MAX_DOCS", 0) or 0),
            "parent_child_auto_merge_enabled": bool(getattr(settings, "RAG_PARENT_CHILD_AUTO_MERGE_ENABLED", False)),
            "parent_child_auto_merge_mode": str(getattr(settings, "RAG_PARENT_CHILD_AUTO_MERGE_MODE", "") or ""),
            "kg_query_expansion_enabled": bool(ctx.kg_query_expansion_enabled),
            "kg_chunk_injection_enabled": bool(ctx.kg_chunk_injection_enabled),
            "kg_chunk_boost_enabled": bool(ctx.kg_chunk_boost_meta.get("enabled")),
            "retrieval_contract_mode": ctx.retrieval_contract_mode or None,
            "retrieval_contract_policy": dict(ctx.retrieval_contract_policy or {}),
            "retrieval_contract_deterministic_recall": bool(ctx.contract_deterministic_recall),
            "retrieval_hard_fallback_enabled": bool(ctx.hard_fallback_enabled),
            "retrieval_hard_fallback_mode": ctx.hard_fallback_mode,
            "retrieval_hard_fallback_top_k": int(ctx.hard_fallback_top_k),
            "adaptive_router": dict(ctx.adaptive_router_meta or {}),
            "channel_budget_policy": dict(ctx.channel_budget_policy_meta or {}),
            "must_recall_enabled": bool(ctx.must_recall_enabled),
            "must_recall_expected_source_keys": list(ctx.must_recall_expected_source_keys or []),
            "must_recall_required_anchor_fields": list(ctx.must_recall_required_anchor_fields or []),
            "must_recall_second_pass_enabled": bool(ctx.must_recall_second_pass_enabled),
            "must_recall_second_pass_mode": str(ctx.must_recall_second_pass_mode),
            "must_recall_second_pass_top_k": int(ctx.must_recall_second_pass_top_k),
            "contextual_followup_enabled": bool(ctx.contextual_followup_enabled),
            "contextual_followup_mode": str(ctx.contextual_followup_mode),
            "contextual_followup_top_k": int(ctx.contextual_followup_top_k),
            "contextual_followup_max_docs": int(ctx.contextual_followup_max_docs),
            "contextual_followup_max_terms": int(ctx.contextual_followup_max_terms),
            "contextual_followup_min_term_chars": int(ctx.contextual_followup_min_term_chars),
            "contextual_followup_max_query_chars": int(ctx.contextual_followup_max_query_chars),
            "contextual_followup_max_hops": int(ctx.contextual_followup_max_hops),
            "contextual_followup_latency_budget_ms": round(float(ctx.contextual_followup_latency_budget_ms), 3),
            "hierarchy_recall_enabled": bool(ctx.hierarchy_recall_enabled),
            "hierarchy_family_collapse": bool(ctx.hierarchy_family_collapse),
            "hierarchy_family_aggregation": str(ctx.hierarchy_family_aggregation),
            "hierarchy_tree_dedup": bool(ctx.hierarchy_tree_dedup),
            "hierarchy_parent_depth": int(ctx.hierarchy_parent_depth),
            "hierarchy_sibling_window": int(ctx.hierarchy_sibling_window),
            "hierarchy_overfetch_factor": int(ctx.hierarchy_overfetch_factor),
            "retrieval_hardcase_emit_enabled": bool(getattr(settings, "RETRIEVAL_HARDCASE_EMIT_ENABLED", False)),
            "rag_evidence_require_spans_enabled": bool(ctx.evidence_span_strict_enabled),
            "retrieval_parse_quality_low_threshold": float(
                getattr(settings, "RETRIEVAL_PARSE_QUALITY_LOW_THRESHOLD", 0.35) or 0.35
            ),
            "retrieval_parse_quality_alert_ratio": float(
                getattr(settings, "RETRIEVAL_PARSE_QUALITY_ALERT_RATIO", 0.5) or 0.5
            ),
            "retrieval_parse_quality_gate_profile": str(ctx.parse_quality_gate_profile),
            "evidence_post_rerank_enabled": bool(getattr(settings, "EVIDENCE_POST_RERANK_ENABLED", False)),
            "evidence_post_rerank_provider": str(getattr(settings, "EVIDENCE_POST_RERANK_PROVIDER", "") or ""),
            "evidence_post_rerank_top_n": int(getattr(settings, "EVIDENCE_POST_RERANK_TOP_N", 0) or 0),
            "evidence_post_rerank_pipeline_enabled": bool(
                getattr(settings, "EVIDENCE_POST_RERANK_PIPELINE_ENABLED", False)
            ),
            "evidence_post_rerank_pipeline": _safe_post_rerank_pipeline_summary(
                getattr(settings, "EVIDENCE_POST_RERANK_PIPELINE", "")
            ),
            "evidence_post_rerank_score_calibration_enabled": bool(
                getattr(settings, "EVIDENCE_POST_RERANK_SCORE_CALIBRATION_ENABLED", False)
            ),
            "evidence_post_rerank_score_calibration_alpha": float(
                getattr(settings, "EVIDENCE_POST_RERANK_SCORE_CALIBRATION_ALPHA", 0.0) or 0.0
            ),
            "multi_query": {
                "enabled": bool(ctx.mq_enabled),
                "count": int(ctx.mq_n or 0),
                "temperature": float(ctx.mq_temp or 0.0),
                "max_chars": int(ctx.mq_max_chars or 0),
                "ab_test_key": ctx.multi_query_ab_test_key,
                "ab_variant": ctx.multi_query_ab_variant,
                "ab_seed": ctx.multi_query_ab_seed,
                "diversify": {
                    "enabled": bool(getattr(settings, "MULTI_QUERY_DIVERSIFY_ENABLED", False)) and bool(ctx.mq_enabled),
                    "budget": max(
                        0,
                        min(
                            int(getattr(settings, "MULTI_QUERY_DIVERSIFY_BUDGET", 0) or 0),
                            int(ctx.top_k or 0),
                        ),
                    ),
                },
            },
            "step_back": {
                "enabled": bool(ctx.step_back_enabled),
                "temperature": float(ctx.step_back_temp or 0.0),
                "max_chars": int(ctx.step_back_max_chars or 0),
                "output_max_chars": int(ctx.step_back_output_max or 0),
            },
            "query_rewrite": {
                "enabled": bool(ctx.rewrite_enabled),
                "strategy_id": ctx.rewrite_strategy_id if ctx.rewrite_enabled else None,
                "strategy_hash": ctx.rewrite_strategy_hash if ctx.rewrite_enabled else None,
                "temperature": ctx.rewrite_temperature if ctx.rewrite_enabled else None,
                "max_chars": int(ctx.rewrite_max_chars or 0) if ctx.rewrite_enabled else None,
            },
            "query_expansion_budget": {
                "max_queries": int(ctx.query_expansion_budget_max_queries or 0),
                "max_candidates": int(ctx.query_expansion_budget_max_candidates or 0),
                "token_budget": int(ctx.query_expansion_budget_token_budget or 0),
                "latency_budget_ms": round(float(ctx.query_expansion_budget_latency_ms or 0.0), 3),
            },
        }

        fp = build_retrieval_config_snapshot(
            RetrievalConfigSnapshotInput(
                retrieval_config=retrieval_cfg,
                rag_config_template=ctx.state.get("rag_config_template"),
            )
        ).fingerprint
        ctx.retrieval_trace["retrieval_config"] = fp
        ctx.metrics["retrieval_config_hash"] = fp.get("hash")
        hc = ctx.metrics.get("hardcase_candidate")
        if isinstance(hc, dict):
            hc["retrieval_config_hash"] = fp.get("hash")
            if not hc.get("dedupe_key"):
                dedupe_payload = {
                    "reason": hc.get("reason"),
                    "query_hash": hc.get("query_hash"),
                    "mode": hc.get("retrieval_mode"),
                    "profile": hc.get("retrieval_profile"),
                    "cfg_hash": fp.get("hash"),
                }
                hc["dedupe_key"] = stable_hash(
                    json.dumps(dedupe_payload, ensure_ascii=False, sort_keys=True),
                    length=32,
                )
            ctx.metrics["hardcase_candidate"] = hc
    except Exception as exc:
        logger.debug(_RETRIEVAL_ORCHESTRATOR_FALLBACK_LOG_MESSAGE, exc)

    return {
        **ctx.state,
        "query_for_retrieval": ctx.query_for_retrieval,
        "docs": ctx.docs,
        "citations": ctx.citations,
        "metrics": ctx.metrics,
        "retrieval_degraded": bool(ctx.retrieval_degraded),
        "fallback_reason": ctx.retrieval_fallback_reason,
        "channel_health": ctx.retrieval_channel_health,
        "abstain_triggered": bool(ctx.abstain_triggered),
        "abstain_reason": ctx.abstain_reason,
        "query_debug": ctx.query_debug,
        "retrieval_trace": ctx.retrieval_trace,
    }
    return None


_RETRIEVAL_RUNTIME_PHASES = (
    _run_retrieval_bootstrap_phase,
    _run_retrieval_alias_dictionary_phase,
    _run_retrieval_kg_query_expansion_phase,
    _run_retrieval_multi_query_phase,
    _run_retrieval_hyde_phase,
    _run_retrieval_step_back_phase,
    _run_retrieval_decomposition_variants_phase,
    _run_retrieval_retrieval_execution_phase,
    _run_retrieval_fusion_phase,
    _run_retrieval_kg_injection_phase,
    _run_retrieval_tag_kg_boost_phase,
    _run_retrieval_post_rerank_hierarchy_setup_phase,
    _run_retrieval_contextual_followup_phase,
    _run_retrieval_citations_hard_fallback_phase,
    _run_retrieval_must_recall_phase,
    _run_retrieval_parse_quality_phase,
    _run_retrieval_metrics_core_phase,
    _run_retrieval_channel_health_phase,
    _run_retrieval_metrics_features_phase,
    _run_retrieval_abstain_hardcase_phase,
    _run_retrieval_query_debug_phase,
    _run_retrieval_retrieval_trace_phase,
    _run_retrieval_config_and_result_phase,
)


def run_retrieval(state: dict[str, Any]) -> dict[str, Any]:
    """Execute retrieval only and return an updated RAG-like state dict."""
    question = str(state.get("question") or "")
    history_text = _build_history_text(state.get("history"))
    no_retrieval_intent = route_intent(question)
    if bool(no_retrieval_intent.get("skip_retrieval")):
        return _build_no_retrieval_response(
            state,
            question=question,
            no_retrieval_intent=dict(no_retrieval_intent),
        )
    runtime = RetrievalRuntimeState(state=state, question=question, history_text=history_text)
    return run_retrieval_runtime(runtime, phases=_RETRIEVAL_RUNTIME_PHASES)


__all__ = ["run_retrieval"]
