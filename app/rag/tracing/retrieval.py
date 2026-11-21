"""Format the completed retrieval state into the stable diagnostic payload."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from langchain_core.documents import Document

from app.infrastructure.config import settings
from app.infrastructure.hashing import stable_hash
from app.rag.retrieval.results import _log_orchestrator_fallback

if TYPE_CHECKING:
    from app.rag.retrieval.stages.state import RetrievalRuntimeState


def _retrieval_variant_counts(retrieval_plan: list[tuple[str, str, Any]]) -> dict[str, int]:
    variants: dict[str, int] = {}
    for kind, _q, _r in retrieval_plan:
        key = kind.strip()
        variants[key] = variants.get(key, 0) + 1
    return variants


def _trace_per_query_item(item: dict[str, Any]) -> dict[str, Any]:
    kind = item["kind"].strip()
    payload: dict[str, Any] = {
        "kind": kind,
        "query_chars": item["query_chars"],
        "ok": item["ok"],
        "elapsed_sec": round(item["elapsed_sec"], 3),
    }
    # The invocation owner has already stripped query text and scope identifiers.
    debug = item["retriever_debug"]
    if debug is not None:
        payload["retriever_debug"] = dict(debug)
    return payload


def _citations_by_role(citations: list[dict[str, Any]]) -> dict[str, int]:
    by_role: dict[str, int] = {}
    for citation in citations:
        # Unannotated citations belong to the main retrieval pass.
        role = (citation.get("retrieval_role") or "main").strip().lower() or "main"
        by_role[role] = by_role.get(role, 0) + 1
    return by_role


def _chunk_quality_summary(docs: list[Document], *, top_k: int) -> dict[str, Any] | None:
    try:
        from app.services.chunking.quality_scoring import summarize_retrieved_chunk_quality

        return summarize_retrieved_chunk_quality(
            docs,
            max_candidates=min(max(1, top_k), 20),
            max_items=8,
        )
    except Exception as exc:  # noqa: BLE001
        _log_orchestrator_fallback("run_retrieval", exc)
        return None


def build_retrieval_trace(ctx: RetrievalRuntimeState) -> dict[str, Any]:
    variants = _retrieval_variant_counts(ctx.retrieval_plan)
    per_query_trace = [_trace_per_query_item(item) for item in ctx.retrieval_per_query[:8]]
    citations_by_role = _citations_by_role(ctx.citations)
    chunk_quality_summary = _chunk_quality_summary(ctx.docs, top_k=ctx.top_k)

    retrieval_trace = {
        "schema": "mimirq.retrieval_trace_pass.v1",
        "query_for_retrieval_hash": stable_hash(ctx.query_for_retrieval),
        "requested_retrieval_mode": ctx.requested_retrieval_mode,
        "retrieval_mode": ctx.request_retrieval_mode,
        "retrieval_mode_auto_routed": ctx.retrieval_mode_routed,
        "retrieval_profile": ctx.profile_norm,
        "retrieval_profile_requested": (
            str(ctx.requested_retrieval_profile).strip().lower()
            if ctx.requested_retrieval_profile is not None
            else None
        ),
        "retrieval_contract_mode": ctx.retrieval_contract_mode,
        "retrieval_contract_policy": dict(ctx.retrieval_contract_policy),
        "retrieval_contract_deterministic_recall": ctx.contract_deterministic_recall,
        "contract_diagnostics": {
            "contract_fail_reason_taxonomy": ctx.retrieval_contract_policy["contract_fail_reason_taxonomy"],
            "must_recall": {
                "enabled": ctx.must_recall_enabled,
                "status": ctx.must_recall_status,
                "passed": ctx.must_recall_passed,
                "expected_source_keys": list(ctx.must_recall_expected_source_keys),
                "missing_source_keys": list(ctx.missing_source_keys)[:40],
                "required_anchor_fields": list(ctx.must_recall_required_anchor_fields),
                "auto_expected_source_keys": {
                    "enabled": ctx.must_recall_auto_expected_source_keys_enabled,
                    "applied": ctx.must_recall_auto_expected_source_keys_applied,
                    "keys": list(ctx.must_recall_auto_expected_source_keys),
                    "reason_codes": list(ctx.must_recall_auto_expected_source_keys_reason_codes),
                    "confidence": str(ctx.must_recall_auto_expected_source_keys_confidence or "none"),
                },
                "auto_required_anchor_fields": {
                    "enabled": ctx.must_recall_auto_required_anchor_fields_enabled,
                    "applied": ctx.must_recall_auto_required_anchor_fields_applied,
                    "fields": list(ctx.must_recall_auto_required_anchor_fields),
                    "reason_codes": list(ctx.must_recall_auto_required_anchor_fields_reason_codes),
                },
                "anchor_missing_counts": dict(ctx.must_recall_anchor_eval["missing_counts"]),
                "fail_reasons": list(ctx.must_recall_fail_reasons)[:12],
                "second_pass": dict(ctx.must_recall_second_pass_payload),
                "proof": dict(ctx.must_recall_proof),
            },
        },
        "intent_router": ctx.intent_router_meta,
        "industry_rules": ctx.industry_rules_meta,
        "adaptive_router": ctx.adaptive_router_meta,
        "channel_budget_policy": ctx.channel_budget_policy_meta,
        "router_layers": ctx.router_layers,
        "contextual_followup": {
            "enabled": ctx.contextual_followup_enabled,
            "attempted": ctx.contextual_followup_attempted,
            "used": ctx.contextual_followup_used,
            "mode": ctx.contextual_followup_mode,
            "top_k": ctx.contextual_followup_top_k,
            "max_docs": ctx.contextual_followup_max_docs,
            "max_terms": ctx.contextual_followup_max_terms,
            "min_term_chars": ctx.contextual_followup_min_term_chars,
            "query_hash": ctx.contextual_followup_query_hash,
            "added_docs": ctx.contextual_followup_added_docs,
            "added_citations": ctx.contextual_followup_added_citations,
            "reason_codes": list(ctx.contextual_followup_reason_codes),
            "selected_terms": list(ctx.contextual_followup_selected_terms)[:10],
            "elapsed_sec": round(ctx.contextual_followup_elapsed, 3),
            "error": ctx.contextual_followup_error,
        },
        "iterative_pass": {
            "enabled": ctx.contextual_followup_enabled,
            "max_hops": ctx.contextual_followup_max_hops,
            "latency_budget_ms": round(ctx.contextual_followup_latency_budget_ms, 3),
            "hops_attempted": sum(hop["attempted"] for hop in ctx.iterative_pass_hops),
            "hops_used": sum(hop["used"] for hop in ctx.iterative_pass_hops),
            "reason_codes": list(ctx.iterative_pass_reason_codes)[:16],
            "gap": dict(ctx.iterative_pass_gap) if ctx.iterative_pass_gap is not None else None,
            "hops": ctx.iterative_pass_hops[:5],
        },
        "hard_fallback": {
            "enabled": ctx.hard_fallback_enabled,
            "attempted": ctx.hard_fallback_attempted,
            "used": ctx.hard_fallback_used,
            "reason": ctx.retrieval_fallback_reason,
            "mode": ctx.hard_fallback_mode,
            "top_k": ctx.hard_fallback_top_k,
            "elapsed_sec": round(ctx.hard_fallback_elapsed, 3),
            "added_docs": ctx.hard_fallback_added_docs,
            "added_citations": ctx.hard_fallback_added_citations,
            "error": ctx.hard_fallback_error,
        },
        "rewrite": {
            "enabled": ctx.rewrite_enabled,
            "strategy_id": ctx.rewrite_strategy_id,
            "strategy_hash": ctx.rewrite_strategy_hash,
            "temperature": ctx.rewrite_temperature if ctx.rewrite_enabled else None,
            "max_chars": ctx.rewrite_max_chars if ctx.rewrite_enabled else None,
            "used": bool(ctx.rewrite_used),
            "elapsed_sec": round(ctx.rewrite_elapsed, 3),
            "model_used": ctx.rewrite_model_used,
        },
        "expansions": {
            "budget": dict(ctx.query_expansion_budget_meta),
            "alias": {
                "enabled": ctx.alias_enabled,
                "used": ctx.alias_used,
                "count": len(ctx.alias_queries),
                "elapsed_sec": round(ctx.alias_elapsed, 3),
            },
            "dict": {
                "enabled": bool(ctx.dict_meta.get("enabled")),
                "used": ctx.dict_used,
                "count": len(ctx.dict_expansions),
                "elapsed_sec": round(ctx.dict_elapsed, 3),
            },
            "kg_query": {
                "enabled": ctx.kg_query_expansion_enabled,
                "used": ctx.kg_query_expansion_used,
                "entities_total": ctx.kg_query_expansion_entities_total,
                "entities_selected": ctx.kg_query_expansion_entities_selected,
                "query_count": len(ctx.kg_query_expansion_queries),
                "elapsed_sec": round(ctx.kg_query_expansion_elapsed, 3),
                "error": ctx.kg_query_expansion_error,
            },
            "clause_fastlane": {
                "used": bool(ctx.clause_fastlane_queries),
                "count": len(ctx.clause_fastlane_queries),
            },
            "lightweight_subquery": {
                "enabled": bool(settings.RETRIEVAL_LIGHTWEIGHT_SUBQUERY_ENABLED),
                "used": bool(ctx.lightweight_subqueries),
                "count": len(ctx.lightweight_subqueries),
            },
            "multi_query": {
                "enabled": ctx.mq_enabled,
                "used": ctx.multi_query_used,
                "count": len(ctx.multi_queries),
                "elapsed_sec": round(ctx.multi_query_elapsed, 3),
                "model_used": ctx.multi_query_model_used,
                "parse_ok": bool(ctx.multi_query_parse_meta.get("ok")),
                "parse_method": ctx.multi_query_parse_meta.get("method"),
                "parse_error": ctx.multi_query_parse_meta.get("error"),
                "ab_test_key": ctx.multi_query_ab_test_key,
                "ab_variant": ctx.multi_query_ab_variant,
                "ab_seed": ctx.multi_query_ab_seed,
                "ab_forced_enable": ctx.multi_query_ab_forced,
            },
            "step_back": {
                "enabled": ctx.step_back_enabled,
                "used": ctx.step_back_used,
                "elapsed_sec": round(ctx.step_back_elapsed, 3),
                "model_used": ctx.step_back_model_used,
                "parse_ok": bool(ctx.step_back_parse_meta.get("ok")),
                "parse_method": ctx.step_back_parse_meta.get("method"),
                "parse_error": ctx.step_back_parse_meta.get("error"),
            },
            "hyde": {
                "enabled": ctx.hyde_enabled,
                "used": ctx.hyde_used,
                "elapsed_sec": round(ctx.hyde_elapsed, 3),
                "model_used": ctx.hyde_model_used,
            },
            "decompose": {
                "enabled": bool(settings.ENABLE_QUERY_DECOMPOSITION),
                "used": ctx.decompose_used,
                "count": len(ctx.sub_questions),
                "elapsed_sec": round(ctx.decompose_elapsed, 3),
                "model_used": ctx.decompose_model_used,
                "parse_ok": bool(ctx.decompose_parse_meta.get("ok")),
                "parse_method": ctx.decompose_parse_meta.get("method"),
                "parse_error": ctx.decompose_parse_meta.get("error"),
            },
        },
        "retrieval": {
            "top_k": ctx.top_k,
            "score_threshold": ctx.retriever_update["score_threshold"],
            "alpha": ctx.retriever_update["alpha"],
            "enable_weight_rerank": ctx.retriever_update["enable_weight_rerank"],
            "vector_weight": ctx.retriever_update["vector_weight"],
            "keyword_weight": ctx.retriever_update["keyword_weight"],
            "channel_fusion_strategy": ctx.retriever_update["fusion_strategy"],
            "channel_fusion_budgets": (
                ctx.retriever_update.get("fusion_budgets")
                if isinstance(ctx.retriever_update.get("fusion_budgets"), dict)
                else None
            ),
            "channel_fusion_min_scores": (
                ctx.retriever_update.get("fusion_min_scores")
                if isinstance(ctx.retriever_update.get("fusion_min_scores"), dict)
                else None
            ),
            "rrf_k": int(settings.RETRIEVAL_RRF_K),
            "query_parallelism": ctx.retrieval_parallelism,
            "query_count": len(ctx.retrieval_plan),
            "query_variants": variants,
            "per_query": per_query_trace,
            "errors": ctx.retrieval_errors[:5],
            "elapsed_sec": round(ctx.retrieval_elapsed, 3),
            "vector_backend": str(settings.VECTOR_BACKEND),
            "retrieval_degraded": ctx.retrieval_degraded,
            "retrieval_degraded_reasons": list(ctx.retrieval_degraded_reason_codes),
            "channel_health": dict(ctx.retrieval_channel_health),
        },
        "query_variant_fusion": {
            "strategy": ("rrf" if len(ctx.docs_by_query) > 1 else "single"),
            "rrf_k": int(settings.RETRIEVAL_RRF_K) if len(ctx.docs_by_query) > 1 else None,
            "multi_query_diversify": {
                "enabled": ctx.mq_diversify_enabled,
                "budget": ctx.mq_diversify_budget if ctx.mq_diversify_enabled else None,
                "used": ctx.mq_diversify_used,
                "selected_mq": ctx.mq_diversify_selected_mq,
                "selected_non_mq": ctx.mq_diversify_selected_non_mq,
                "fill_from_fused": ctx.mq_diversify_fill_from_fused,
            },
        },
        "hierarchy_recall": {
            "enabled": ctx.hierarchy_recall_enabled,
            "family_collapse": ctx.hierarchy_family_collapse,
            "family_aggregation": ctx.hierarchy_family_aggregation,
            "tree_dedup": ctx.hierarchy_tree_dedup,
            "parent_depth": ctx.hierarchy_parent_depth,
            "sibling_window": ctx.hierarchy_sibling_window,
            "overfetch_factor": ctx.hierarchy_overfetch_factor,
        },
        "kg_chunk_injection": {
            "enabled": ctx.kg_chunk_injection_enabled,
            "max_chunks": ctx.kg_chunk_injection_max_chunks,
            "chunks_injected": ctx.kg_chunks_injected,
            "boost": dict(ctx.kg_chunk_boost_meta),
            "error": ctx.kg_chunk_injection_error,
        },
        "post_rerank": {
            "enabled": ctx.post_rerank_enabled,
            "used": ctx.post_rerank_used,
            "provider": ctx.post_rerank_provider,
            "skip_reason": ctx.post_rerank_skip_reason,
            "cache": {
                "enabled": ctx.post_rerank_cache_enabled,
                "backend": ctx.post_rerank_cache_backend,
                "hits": ctx.post_rerank_cache_hits,
                "misses": ctx.post_rerank_cache_misses,
            },
            "pipeline_enabled": ctx.post_rerank_pipeline_enabled,
            "pipeline_used": ctx.post_rerank_pipeline_used,
            "pipeline": ctx.post_rerank_pipeline[:4],
            "pipeline_stages": ctx.post_rerank_pipeline_stages[:4],
            "candidates_n": ctx.post_rerank_candidates_n,
            "elapsed_sec": round(ctx.post_rerank_elapsed, 3),
            "model_used": ctx.post_rerank_model_used,
            "score_calibration": dict(ctx.post_rerank_score_calibration_stats),
            "error": ctx.post_rerank_error,
        },
        "abstain": {
            "enabled": ctx.abstain_enabled,
            "triggered": ctx.abstain_triggered,
            "reason": ctx.abstain_reason,
            "evidence_span_strict_enabled": ctx.evidence_span_strict_enabled,
            "evidence_span_missing_citations": ctx.evidence_span_missing_citations,
            "min_citations": int(settings.RAG_ABSTAIN_MIN_CITATIONS),
            "min_top_relevance_score": float(settings.RAG_ABSTAIN_MIN_TOP_RELEVANCE_SCORE),
            "top_relevance_score": round(ctx.top_rel, 3),
        },
        "fallback_reason": ctx.retrieval_fallback_reason,
        "citations": {
            "count": len(ctx.citations),
            "by_role": citations_by_role,
            "chunk_quality": chunk_quality_summary,
        },
        "parse_quality": dict(ctx.parse_quality_summary),
        "parse_quality_gate": {
            "profile": ctx.parse_quality_gate_profile,
            "violation": ctx.parse_quality_gate_violation,
            "blocked": ctx.parse_quality_gate_blocked,
            "reason": ctx.parse_quality_gate_reason,
        },
        "parse_risk": dict(ctx.parse_risk),
        "parse_risk_auto_enqueue_policy": (
            dict(ctx.metrics.get("parse_risk_auto_enqueue_policy"))
            if isinstance(ctx.metrics.get("parse_risk_auto_enqueue_policy"), dict)
            else None
        ),
        "parse_repair_actions": (
            dict(ctx.metrics.get("parse_repair_actions"))
            if isinstance(ctx.metrics.get("parse_repair_actions"), dict)
            else None
        ),
        "hardcase_candidate": (
            ctx.metrics.get("hardcase_candidate") if isinstance(ctx.metrics.get("hardcase_candidate"), dict) else None
        ),
    }
    return retrieval_trace
