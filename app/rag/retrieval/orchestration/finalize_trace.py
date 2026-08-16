"""Stable retrieval-trace formatter split from ``app.rag.retrieval.orchestrator``."""

from dataclasses import dataclass
from typing import Any

from langchain_core.documents import Document

from app.core.config import settings
from app.rag.core.hashing import stable_hash
from app.rag.policy.must_recall import MUST_RECALL_FAIL_REASON_TAXONOMY_V1
from app.rag.retrieval.orchestration.common import _log_orchestrator_fallback


@dataclass(frozen=True)
class RetrievalTraceStageInput:
    query_for_retrieval: str
    requested_retrieval_mode: Any
    request_retrieval_mode: str
    retrieval_mode_routed: bool
    requested_retrieval_profile: Any
    profile_norm: str | None
    retrieval_contract_mode: str | None
    retrieval_contract_policy: dict[str, Any]
    contract_deterministic_recall: bool
    must_recall_enabled: bool
    must_recall_status: str
    must_recall_passed: bool
    must_recall_expected_source_keys: list[str]
    missing_source_keys: list[str]
    must_recall_required_anchor_fields: list[str]
    must_recall_auto_expected_source_keys_enabled: bool
    must_recall_auto_expected_source_keys_applied: bool
    must_recall_auto_expected_source_keys: list[str]
    must_recall_auto_expected_source_keys_reason_codes: list[str]
    must_recall_auto_expected_source_keys_confidence: str | None
    must_recall_auto_required_anchor_fields_enabled: bool
    must_recall_auto_required_anchor_fields_applied: bool
    must_recall_auto_required_anchor_fields: list[str]
    must_recall_auto_required_anchor_fields_reason_codes: list[str]
    must_recall_anchor_eval: dict[str, Any]
    must_recall_fail_reasons: list[str]
    must_recall_second_pass_payload: dict[str, Any]
    must_recall_proof: dict[str, Any]
    intent_router_meta: dict[str, Any]
    industry_rules_meta: dict[str, Any]
    adaptive_router_meta: dict[str, Any]
    channel_budget_policy_meta: dict[str, Any]
    router_layers: dict[str, Any]
    contextual_followup_enabled: bool
    contextual_followup_attempted: bool
    contextual_followup_used: bool
    contextual_followup_mode: str
    contextual_followup_top_k: int
    contextual_followup_max_docs: int
    contextual_followup_max_terms: int
    contextual_followup_min_term_chars: int
    contextual_followup_query_hash: str | None
    contextual_followup_added_docs: int
    contextual_followup_added_citations: int
    contextual_followup_reason_codes: list[str]
    contextual_followup_selected_terms: list[str]
    contextual_followup_elapsed: float
    contextual_followup_error: str | None
    contextual_followup_max_hops: int
    contextual_followup_latency_budget_ms: float
    iterative_pass_hops: list[dict[str, Any]]
    iterative_pass_reason_codes: list[str]
    iterative_pass_gap: dict[str, Any] | None
    hard_fallback_enabled: bool
    hard_fallback_attempted: bool
    hard_fallback_used: bool
    retrieval_fallback_reason: str | None
    hard_fallback_mode: str
    hard_fallback_top_k: int
    hard_fallback_elapsed: float
    hard_fallback_added_docs: int
    hard_fallback_added_citations: int
    hard_fallback_error: str | None
    rewrite_enabled: bool
    rewrite_strategy_id: str | None
    rewrite_strategy_hash: str | None
    rewrite_temperature: float | None
    rewrite_max_chars: int | None
    rewrite_used: bool
    rewrite_elapsed: float
    rewrite_model_used: Any
    query_expansion_budget_meta: dict[str, Any]
    alias_enabled: bool
    alias_used: bool
    alias_queries: list[str]
    alias_elapsed: float
    dict_meta: dict[str, Any]
    dict_used: bool
    dict_expansions: list[dict[str, Any]]
    dict_elapsed: float
    kg_query_expansion_enabled: bool
    kg_query_expansion_used: bool
    kg_query_expansion_entities_total: int
    kg_query_expansion_entities_selected: int
    kg_query_expansion_queries: list[str]
    kg_query_expansion_elapsed: float
    kg_query_expansion_error: str | None
    clause_fastlane_queries: list[str]
    lightweight_subqueries: list[str]
    mq_enabled: bool
    multi_query_used: bool
    multi_queries: list[str]
    multi_query_elapsed: float
    multi_query_model_used: Any
    multi_query_parse_meta: dict[str, Any]
    multi_query_ab_test_key: str | None
    multi_query_ab_variant: str | None
    multi_query_ab_seed: int | None
    multi_query_ab_forced: bool
    step_back_enabled: bool
    step_back_used: bool
    step_back_elapsed: float
    step_back_model_used: Any
    step_back_parse_meta: dict[str, Any]
    hyde_enabled: bool
    hyde_used: bool
    hyde_elapsed: float
    hyde_model_used: Any
    decompose_used: bool
    sub_questions: list[str]
    decompose_elapsed: float
    decompose_model_used: Any
    decompose_parse_meta: dict[str, Any]
    top_k: int
    retriever_update: dict[str, Any]
    retrieval_parallelism: int
    retrieval_plan: list[tuple[Any, Any, Any]]
    retrieval_per_query: list[dict[str, Any]]
    retrieval_errors: list[dict[str, Any]]
    retrieval_elapsed: float
    retrieval_degraded: bool
    retrieval_degraded_reason_codes: list[str]
    retrieval_channel_health: dict[str, Any]
    docs_by_query: Any
    mq_diversify_enabled: bool
    mq_diversify_budget: int
    mq_diversify_used: bool
    mq_diversify_selected_mq: int
    mq_diversify_selected_non_mq: int
    mq_diversify_fill_from_fused: int
    hierarchy_recall_enabled: bool
    hierarchy_family_collapse: bool
    hierarchy_family_aggregation: str
    hierarchy_tree_dedup: bool
    hierarchy_parent_depth: int
    hierarchy_sibling_window: int
    hierarchy_overfetch_factor: int
    kg_chunk_injection_enabled: bool
    kg_chunk_injection_max_chunks: int
    kg_chunks_injected: int
    kg_chunk_boost_meta: dict[str, Any]
    kg_chunk_injection_error: str | None
    post_rerank_enabled: bool
    post_rerank_used: bool
    post_rerank_provider: str | None
    post_rerank_skip_reason: str | None
    post_rerank_cache_enabled: bool
    post_rerank_cache_backend: str | None
    post_rerank_cache_hits: int
    post_rerank_cache_misses: int
    post_rerank_pipeline_enabled: bool
    post_rerank_pipeline_used: bool
    post_rerank_pipeline: list[Any]
    post_rerank_pipeline_stages: list[Any]
    post_rerank_candidates_n: int
    post_rerank_elapsed: float
    post_rerank_model_used: Any
    post_rerank_score_calibration_stats: dict[str, Any]
    post_rerank_error: str | None
    abstain_enabled: bool
    abstain_triggered: bool
    abstain_reason: str | None
    evidence_span_strict_enabled: bool
    evidence_span_missing_citations: int
    top_rel: float
    citations: list[dict[str, Any]]
    docs: list[Document]
    parse_quality_summary: dict[str, Any]
    parse_quality_gate_profile: str
    parse_quality_gate_violation: bool
    parse_quality_gate_blocked: bool
    parse_quality_gate_reason: str | None
    parse_risk: dict[str, Any]
    metrics: dict[str, Any]


@dataclass(frozen=True)
class RetrievalTraceStageOutput:
    retrieval_trace: dict[str, Any]


def _retrieval_variant_counts(retrieval_plan: list[tuple[Any, Any, Any]]) -> dict[str, int]:
    try:
        variants: dict[str, int] = {}
        for kind, _q, _r in retrieval_plan:
            key = str(kind or "").strip() or "main"
            variants[key] = int(variants.get(key, 0) or 0) + 1
        return variants
    except (TypeError, ValueError, AttributeError):
        return {}


def _trace_per_query_item(item: dict[str, Any]) -> dict[str, Any]:
    kind = str(item.get("kind") or "").strip() or "main"
    payload: dict[str, Any] = {
        "kind": kind,
        "query_chars": int(item.get("query_chars") or 0),
        "ok": bool(item.get("ok")),
        "elapsed_sec": round(float(item.get("elapsed_sec") or 0.0), 3),
    }
    dbg = item.get("retriever_debug")
    if isinstance(dbg, dict):
        dbg_copy = dict(dbg)
        query_normalization = dbg_copy.get("query_normalization")
        if isinstance(query_normalization, dict):
            query_normalization_copy = dict(query_normalization)
            query_normalization_copy.pop("normalized", None)
            if query_normalization_copy:
                dbg_copy["query_normalization"] = query_normalization_copy
            else:
                dbg_copy.pop("query_normalization", None)
        payload["retriever_debug"] = dbg_copy
    return payload


def _per_query_trace(retrieval_per_query: list[dict[str, Any]]) -> list[dict[str, Any]]:
    try:
        return [_trace_per_query_item(item) for item in retrieval_per_query if isinstance(item, dict)]
    except Exception as exc:  # noqa: BLE001
        _log_orchestrator_fallback("run_retrieval", exc)
        return []


def _citations_by_role(citations: list[dict[str, Any]]) -> dict[str, int]:
    try:
        by_role: dict[str, int] = {}
        for citation in citations:
            if not isinstance(citation, dict):
                continue
            role = str(citation.get("retrieval_role") or "main").strip().lower() or "main"
            by_role[role] = int(by_role.get(role, 0) or 0) + 1
        return by_role
    except (TypeError, ValueError, AttributeError):
        return {}


def _chunk_quality_summary(docs: list[Document], *, top_k: int) -> dict[str, Any] | None:
    try:
        from app.services.chunk_quality_scoring import summarize_retrieved_chunk_quality

        return summarize_retrieved_chunk_quality(
            docs,
            max_candidates=min(max(1, int(top_k or 0)), 20),
            max_items=8,
        )
    except Exception as exc:  # noqa: BLE001
        _log_orchestrator_fallback("run_retrieval", exc)
        return None


def build_retrieval_trace_stage(payload: RetrievalTraceStageInput) -> RetrievalTraceStageOutput:
    variants = _retrieval_variant_counts(payload.retrieval_plan)
    per_query_trace = _per_query_trace(payload.retrieval_per_query)
    citations_by_role = _citations_by_role(payload.citations)
    chunk_quality_summary = _chunk_quality_summary(payload.docs, top_k=payload.top_k)

    retrieval_trace = {
        "schema": "mimirq.retrieval_trace_pass.v1",
        "query_for_retrieval_hash": stable_hash(payload.query_for_retrieval),
        "requested_retrieval_mode": str(payload.requested_retrieval_mode or ""),
        "retrieval_mode": str(payload.request_retrieval_mode or ""),
        "retrieval_mode_auto_routed": bool(payload.retrieval_mode_routed),
        "retrieval_profile": payload.profile_norm or None,
        "retrieval_profile_requested": (
            str(payload.requested_retrieval_profile).strip().lower()
            if payload.requested_retrieval_profile is not None
            else None
        ),
        "retrieval_contract_mode": payload.retrieval_contract_mode or None,
        "retrieval_contract_policy": dict(payload.retrieval_contract_policy or {}),
        "retrieval_contract_deterministic_recall": bool(payload.contract_deterministic_recall),
        "contract_diagnostics": {
            "contract_fail_reason_taxonomy": str(
                payload.retrieval_contract_policy.get("contract_fail_reason_taxonomy")
                or MUST_RECALL_FAIL_REASON_TAXONOMY_V1
            ),
            "must_recall": {
                "enabled": bool(payload.must_recall_enabled),
                "status": str(payload.must_recall_status),
                "passed": bool(payload.must_recall_passed),
                "expected_source_keys": list(payload.must_recall_expected_source_keys or []),
                "missing_source_keys": list(payload.missing_source_keys or [])[:40],
                "required_anchor_fields": list(payload.must_recall_required_anchor_fields or []),
                "auto_expected_source_keys": {
                    "enabled": bool(payload.must_recall_auto_expected_source_keys_enabled),
                    "applied": bool(payload.must_recall_auto_expected_source_keys_applied),
                    "keys": list(payload.must_recall_auto_expected_source_keys or []),
                    "reason_codes": list(payload.must_recall_auto_expected_source_keys_reason_codes or []),
                    "confidence": str(payload.must_recall_auto_expected_source_keys_confidence or "none"),
                },
                "auto_required_anchor_fields": {
                    "enabled": bool(payload.must_recall_auto_required_anchor_fields_enabled),
                    "applied": bool(payload.must_recall_auto_required_anchor_fields_applied),
                    "fields": list(payload.must_recall_auto_required_anchor_fields or []),
                    "reason_codes": list(payload.must_recall_auto_required_anchor_fields_reason_codes or []),
                },
                "anchor_missing_counts": dict(payload.must_recall_anchor_eval.get("missing_counts") or {}),
                "fail_reasons": list(payload.must_recall_fail_reasons or [])[:12],
                "second_pass": dict(payload.must_recall_second_pass_payload),
                "proof": dict(payload.must_recall_proof),
            },
        },
        "intent_router": payload.intent_router_meta,
        "industry_rules": payload.industry_rules_meta,
        "adaptive_router": payload.adaptive_router_meta,
        "channel_budget_policy": payload.channel_budget_policy_meta,
        "router_layers": payload.router_layers,
        "contextual_followup": {
            "enabled": bool(payload.contextual_followup_enabled),
            "attempted": bool(payload.contextual_followup_attempted),
            "used": bool(payload.contextual_followup_used),
            "mode": str(payload.contextual_followup_mode),
            "top_k": int(payload.contextual_followup_top_k),
            "max_docs": int(payload.contextual_followup_max_docs),
            "max_terms": int(payload.contextual_followup_max_terms),
            "min_term_chars": int(payload.contextual_followup_min_term_chars),
            "query_hash": payload.contextual_followup_query_hash,
            "added_docs": int(payload.contextual_followup_added_docs),
            "added_citations": int(payload.contextual_followup_added_citations),
            "reason_codes": list(payload.contextual_followup_reason_codes or []),
            "selected_terms": list(payload.contextual_followup_selected_terms or [])[:10],
            "elapsed_sec": round(float(payload.contextual_followup_elapsed or 0.0), 3),
            "error": payload.contextual_followup_error,
        },
        "iterative_pass": {
            "enabled": bool(payload.contextual_followup_enabled),
            "max_hops": int(payload.contextual_followup_max_hops),
            "latency_budget_ms": round(float(payload.contextual_followup_latency_budget_ms), 3),
            "hops_attempted": int(
                len([hop for hop in payload.iterative_pass_hops if isinstance(hop, dict) and bool(hop.get("attempted"))])
            ),
            "hops_used": int(
                len([hop for hop in payload.iterative_pass_hops if isinstance(hop, dict) and bool(hop.get("used"))])
            ),
            "reason_codes": list(payload.iterative_pass_reason_codes or [])[:16],
            "gap": (dict(payload.iterative_pass_gap or {}) if isinstance(payload.iterative_pass_gap, dict) else None),
            "hops": [hop for hop in list(payload.iterative_pass_hops or [])[:5] if isinstance(hop, dict)],
        },
        "hard_fallback": {
            "enabled": bool(payload.hard_fallback_enabled),
            "attempted": bool(payload.hard_fallback_attempted),
            "used": bool(payload.hard_fallback_used),
            "reason": payload.retrieval_fallback_reason,
            "mode": payload.hard_fallback_mode,
            "top_k": int(payload.hard_fallback_top_k),
            "elapsed_sec": round(float(payload.hard_fallback_elapsed or 0.0), 3),
            "added_docs": int(payload.hard_fallback_added_docs or 0),
            "added_citations": int(payload.hard_fallback_added_citations or 0),
            "error": payload.hard_fallback_error,
        },
        "rewrite": {
            "enabled": bool(payload.rewrite_enabled),
            "strategy_id": payload.rewrite_strategy_id,
            "strategy_hash": payload.rewrite_strategy_hash,
            "temperature": payload.rewrite_temperature if payload.rewrite_enabled else None,
            "max_chars": int(payload.rewrite_max_chars or 0) if payload.rewrite_enabled else None,
            "used": bool(payload.rewrite_used),
            "elapsed_sec": round(float(payload.rewrite_elapsed or 0.0), 3),
            "model_used": payload.rewrite_model_used,
        },
        "expansions": {
            "budget": dict(payload.query_expansion_budget_meta),
            "alias": {
                "enabled": bool(payload.alias_enabled),
                "used": bool(payload.alias_used),
                "count": int(len(payload.alias_queries)),
                "elapsed_sec": round(float(payload.alias_elapsed or 0.0), 3),
            },
            "dict": {
                "enabled": bool(payload.dict_meta.get("enabled")),
                "used": bool(payload.dict_used),
                "count": int(len(payload.dict_expansions)),
                "elapsed_sec": round(float(payload.dict_elapsed or 0.0), 3),
            },
            "kg_query": {
                "enabled": bool(payload.kg_query_expansion_enabled),
                "used": bool(payload.kg_query_expansion_used),
                "entities_total": int(payload.kg_query_expansion_entities_total),
                "entities_selected": int(payload.kg_query_expansion_entities_selected),
                "query_count": int(len(payload.kg_query_expansion_queries)),
                "elapsed_sec": round(float(payload.kg_query_expansion_elapsed or 0.0), 3),
                "error": payload.kg_query_expansion_error,
            },
            "clause_fastlane": {
                "used": bool(payload.clause_fastlane_queries),
                "count": int(len(payload.clause_fastlane_queries)),
            },
            "lightweight_subquery": {
                "enabled": bool(getattr(settings, "RETRIEVAL_LIGHTWEIGHT_SUBQUERY_ENABLED", False)),
                "used": bool(payload.lightweight_subqueries),
                "count": int(len(payload.lightweight_subqueries)),
            },
            "multi_query": {
                "enabled": bool(payload.mq_enabled),
                "used": bool(payload.multi_query_used),
                "count": int(len(payload.multi_queries)),
                "elapsed_sec": round(float(payload.multi_query_elapsed or 0.0), 3),
                "model_used": payload.multi_query_model_used,
                "parse_ok": bool(payload.multi_query_parse_meta.get("ok")),
                "parse_method": payload.multi_query_parse_meta.get("method"),
                "parse_error": payload.multi_query_parse_meta.get("error"),
                "ab_test_key": payload.multi_query_ab_test_key,
                "ab_variant": payload.multi_query_ab_variant,
                "ab_seed": payload.multi_query_ab_seed,
                "ab_forced_enable": bool(payload.multi_query_ab_forced),
            },
            "step_back": {
                "enabled": bool(payload.step_back_enabled),
                "used": bool(payload.step_back_used),
                "elapsed_sec": round(float(payload.step_back_elapsed or 0.0), 3),
                "model_used": payload.step_back_model_used,
                "parse_ok": bool(payload.step_back_parse_meta.get("ok")),
                "parse_method": payload.step_back_parse_meta.get("method"),
                "parse_error": payload.step_back_parse_meta.get("error"),
            },
            "hyde": {
                "enabled": bool(payload.hyde_enabled),
                "used": bool(payload.hyde_used),
                "elapsed_sec": round(float(payload.hyde_elapsed or 0.0), 3),
                "model_used": payload.hyde_model_used,
            },
            "decompose": {
                "enabled": bool(settings.ENABLE_QUERY_DECOMPOSITION),
                "used": bool(payload.decompose_used),
                "count": int(len(payload.sub_questions)),
                "elapsed_sec": round(float(payload.decompose_elapsed or 0.0), 3),
                "model_used": payload.decompose_model_used,
                "parse_ok": bool(payload.decompose_parse_meta.get("ok")),
                "parse_method": payload.decompose_parse_meta.get("method"),
                "parse_error": payload.decompose_parse_meta.get("error"),
            },
        },
        "retrieval": {
            "top_k": int(payload.top_k),
            "score_threshold": float(payload.retriever_update.get("score_threshold") or 0.0),
            "alpha": float(payload.retriever_update.get("alpha") or 0.0),
            "enable_weight_rerank": bool(payload.retriever_update.get("enable_weight_rerank", True)),
            "vector_weight": float(payload.retriever_update.get("vector_weight") or 0.0),
            "keyword_weight": float(payload.retriever_update.get("keyword_weight") or 0.0),
            "channel_fusion_strategy": str(payload.retriever_update.get("fusion_strategy") or "linear"),
            "channel_fusion_budgets": (
                payload.retriever_update.get("fusion_budgets")
                if isinstance(payload.retriever_update.get("fusion_budgets"), dict)
                else None
            ),
            "channel_fusion_min_scores": (
                payload.retriever_update.get("fusion_min_scores")
                if isinstance(payload.retriever_update.get("fusion_min_scores"), dict)
                else None
            ),
            "rrf_k": int(getattr(settings, "RETRIEVAL_RRF_K", 60) or 60),
            "query_parallelism": int(payload.retrieval_parallelism),
            "query_count": int(len(payload.retrieval_plan)),
            "query_variants": variants,
            "per_query": per_query_trace[:8],
            "errors": payload.retrieval_errors[:5],
            "elapsed_sec": round(float(payload.retrieval_elapsed or 0.0), 3),
            "vector_backend": str(getattr(settings, "VECTOR_BACKEND", "") or ""),
            "retrieval_degraded": bool(payload.retrieval_degraded),
            "retrieval_degraded_reasons": list(payload.retrieval_degraded_reason_codes or []),
            "channel_health": dict(payload.retrieval_channel_health),
        },
        "query_variant_fusion": {
            "strategy": ("rrf" if len(payload.docs_by_query) > 1 else "single"),
            "rrf_k": int(settings.RETRIEVAL_RRF_K or 0) if len(payload.docs_by_query) > 1 else None,
            "multi_query_diversify": {
                "enabled": bool(payload.mq_diversify_enabled),
                "budget": int(payload.mq_diversify_budget or 0) if payload.mq_diversify_enabled else None,
                "used": bool(payload.mq_diversify_used),
                "selected_mq": int(payload.mq_diversify_selected_mq or 0),
                "selected_non_mq": int(payload.mq_diversify_selected_non_mq or 0),
                "fill_from_fused": int(payload.mq_diversify_fill_from_fused or 0),
            },
        },
        "hierarchy_recall": {
            "enabled": bool(payload.hierarchy_recall_enabled),
            "family_collapse": bool(payload.hierarchy_family_collapse),
            "family_aggregation": str(payload.hierarchy_family_aggregation),
            "tree_dedup": bool(payload.hierarchy_tree_dedup),
            "parent_depth": int(payload.hierarchy_parent_depth),
            "sibling_window": int(payload.hierarchy_sibling_window),
            "overfetch_factor": int(payload.hierarchy_overfetch_factor),
        },
        "kg_chunk_injection": {
            "enabled": bool(payload.kg_chunk_injection_enabled),
            "max_chunks": int(payload.kg_chunk_injection_max_chunks),
            "chunks_injected": int(payload.kg_chunks_injected or 0),
            "boost": dict(payload.kg_chunk_boost_meta or {}),
            "error": payload.kg_chunk_injection_error,
        },
        "post_rerank": {
            "enabled": bool(payload.post_rerank_enabled),
            "used": bool(payload.post_rerank_used),
            "provider": payload.post_rerank_provider,
            "skip_reason": payload.post_rerank_skip_reason,
            "cache": {
                "enabled": bool(payload.post_rerank_cache_enabled),
                "backend": payload.post_rerank_cache_backend,
                "hits": int(payload.post_rerank_cache_hits or 0),
                "misses": int(payload.post_rerank_cache_misses or 0),
            },
            "pipeline_enabled": bool(payload.post_rerank_pipeline_enabled),
            "pipeline_used": bool(payload.post_rerank_pipeline_used),
            "pipeline": payload.post_rerank_pipeline[:4],
            "pipeline_stages": payload.post_rerank_pipeline_stages[:4],
            "candidates_n": int(payload.post_rerank_candidates_n or 0),
            "elapsed_sec": round(float(payload.post_rerank_elapsed or 0.0), 3),
            "model_used": payload.post_rerank_model_used,
            "score_calibration": dict(payload.post_rerank_score_calibration_stats or {}),
            "error": payload.post_rerank_error,
        },
        "abstain": {
            "enabled": bool(payload.abstain_enabled),
            "triggered": bool(payload.abstain_triggered),
            "reason": payload.abstain_reason,
            "evidence_span_strict_enabled": bool(payload.evidence_span_strict_enabled),
            "evidence_span_missing_citations": int(payload.evidence_span_missing_citations or 0),
            "min_citations": int(settings.RAG_ABSTAIN_MIN_CITATIONS or 0),
            "min_top_relevance_score": float(settings.RAG_ABSTAIN_MIN_TOP_RELEVANCE_SCORE or 0.0),
            "top_relevance_score": round(float(payload.top_rel or 0.0), 3),
        },
        "fallback_reason": payload.retrieval_fallback_reason,
        "citations": {
            "count": int(len(payload.citations)),
            "by_role": citations_by_role,
            "chunk_quality": chunk_quality_summary,
        },
        "parse_quality": dict(payload.parse_quality_summary or {}),
        "parse_quality_gate": {
            "profile": str(payload.parse_quality_gate_profile),
            "violation": bool(payload.parse_quality_gate_violation),
            "blocked": bool(payload.parse_quality_gate_blocked),
            "reason": payload.parse_quality_gate_reason,
        },
        "parse_risk": dict(payload.parse_risk or {}),
        "parse_risk_auto_enqueue_policy": (
            dict(payload.metrics.get("parse_risk_auto_enqueue_policy"))
            if isinstance(payload.metrics.get("parse_risk_auto_enqueue_policy"), dict)
            else None
        ),
        "parse_repair_actions": (
            dict(payload.metrics.get("parse_repair_actions"))
            if isinstance(payload.metrics.get("parse_repair_actions"), dict)
            else None
        ),
        "hardcase_candidate": (
            payload.metrics.get("hardcase_candidate")
            if isinstance(payload.metrics.get("hardcase_candidate"), dict)
            else None
        ),
    }
    return RetrievalTraceStageOutput(retrieval_trace=retrieval_trace)
