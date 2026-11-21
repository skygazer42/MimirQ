"""Snapshot the effective retrieval configuration and finalize the result."""

import json
import logging
from typing import Any

from app.infrastructure.config import settings
from app.infrastructure.hashing import stable_hash
from app.rag.retrieval.configuration.fingerprint import RetrievalConfigSnapshotInput, build_retrieval_config_snapshot
from app.rag.retrieval.reranking.providers import describe_reranker_provider
from app.rag.retrieval.results import _RETRIEVAL_ORCHESTRATOR_FALLBACK_LOG_MESSAGE
from app.rag.retrieval.stages.state import RetrievalRuntimeState

logger = logging.getLogger("app.rag.retrieval.orchestrator")


def _run_retrieval_config_and_result_phase(ctx: RetrievalRuntimeState) -> dict[str, Any]:
    try:
        retrieval_cfg: dict[str, Any] = {
            "requested_retrieval_mode": ctx.requested_retrieval_mode,
            "retrieval_mode": ctx.request_retrieval_mode,
            "retrieval_mode_auto_routed": bool(ctx.retrieval_mode_routed),
            "retrieval_profile": ctx.profile_norm,
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
            "reranker_provider": ctx.retriever_update.get("reranker_provider"),
            "reranker_tier": describe_reranker_provider(
                ctx.retriever_update.get("reranker_provider"),
            ).get("tier"),
            "reranker_top_n": int(ctx.retriever_update.get("reranker_top_n") or 0),
            "visible_evidence_only": bool(ctx.strict_visible),
            # Global retrieval channel toggles (low-cardinality).
            "vector_backend": str(settings.VECTOR_BACKEND),
            "bm25_enabled": bool(settings.BM25_INDEX_ENABLED),
            "lexical_enabled": bool(settings.LEXICAL_DB_TRGM_ENABLED),
            "parent_child_auto_merge_enabled": bool(settings.RAG_PARENT_CHILD_AUTO_MERGE_ENABLED),
            "parent_child_auto_merge_mode": str(settings.RAG_PARENT_CHILD_AUTO_MERGE_MODE),
            "kg_query_expansion_enabled": bool(ctx.kg_query_expansion_enabled),
            "kg_chunk_injection_enabled": bool(ctx.kg_chunk_injection_enabled),
            "kg_chunk_boost_enabled": bool(ctx.kg_chunk_boost_meta.get("enabled")),
            "retrieval_contract_mode": ctx.retrieval_contract_mode,
            "retrieval_contract_policy": dict(ctx.retrieval_contract_policy),
            "retrieval_contract_deterministic_recall": bool(ctx.contract_deterministic_recall),
            "retrieval_hard_fallback_enabled": bool(ctx.hard_fallback_enabled),
            "retrieval_hard_fallback_mode": ctx.hard_fallback_mode,
            "retrieval_hard_fallback_top_k": int(ctx.hard_fallback_top_k),
            "adaptive_router": dict(ctx.adaptive_router_meta or {}),
            "channel_budget_policy": dict(ctx.channel_budget_policy_meta or {}),
            "must_recall_enabled": bool(ctx.must_recall_enabled),
            "must_recall_expected_source_keys": list(ctx.must_recall_expected_source_keys),
            "must_recall_required_anchor_fields": list(ctx.must_recall_required_anchor_fields),
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
            "retrieval_hardcase_emit_enabled": bool(settings.RETRIEVAL_HARDCASE_EMIT_ENABLED),
            "rag_evidence_require_spans_enabled": bool(ctx.evidence_span_strict_enabled),
            "retrieval_parse_quality_low_threshold": float(settings.RETRIEVAL_PARSE_QUALITY_LOW_THRESHOLD),
            "retrieval_parse_quality_alert_ratio": float(settings.RETRIEVAL_PARSE_QUALITY_ALERT_RATIO),
            "retrieval_parse_quality_gate_profile": str(ctx.parse_quality_gate_profile),
            "evidence_post_rerank_enabled": bool(settings.EVIDENCE_POST_RERANK_ENABLED),
            "evidence_post_rerank_provider": str(settings.EVIDENCE_POST_RERANK_PROVIDER),
            "evidence_post_rerank_top_n": int(settings.EVIDENCE_POST_RERANK_TOP_N),
            "evidence_post_rerank_pipeline_enabled": bool(settings.EVIDENCE_POST_RERANK_PIPELINE_ENABLED),
            "evidence_post_rerank_pipeline": [stage.model_dump() for stage in settings.EVIDENCE_POST_RERANK_PIPELINE],
            "evidence_post_rerank_score_calibration_enabled": bool(
                settings.EVIDENCE_POST_RERANK_SCORE_CALIBRATION_ENABLED
            ),
            "evidence_post_rerank_score_calibration_alpha": float(
                settings.EVIDENCE_POST_RERANK_SCORE_CALIBRATION_ALPHA
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
                    "enabled": bool(settings.MULTI_QUERY_DIVERSIFY_ENABLED) and bool(ctx.mq_enabled),
                    "budget": max(
                        0,
                        min(
                            int(settings.MULTI_QUERY_DIVERSIFY_BUDGET),
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
        ctx.metrics["retrieval_config_hash"] = fp["hash"]
        hc = ctx.metrics.get("hardcase_candidate")
        if isinstance(hc, dict):
            hc["retrieval_config_hash"] = fp["hash"]
            if not hc.get("dedupe_key"):
                dedupe_payload = {
                    "reason": hc.get("reason"),
                    "query_hash": hc.get("query_hash"),
                    "mode": hc.get("retrieval_mode"),
                    "profile": hc.get("retrieval_profile"),
                    "cfg_hash": fp["hash"],
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
