"""Collect parse quality, retrieval metrics and channel health."""

from typing import Any

from app.infrastructure.config import settings
from app.rag.retrieval.evidence.quality import (
    _classify_parse_risk,
    _diagnose_empty_retrieval,
    _sanitize_parse_repair_actions,
    _summarize_parse_quality_risk,
)
from app.rag.retrieval.stages.state import RetrievalRuntimeState


def _run_retrieval_parse_quality_phase(ctx: RetrievalRuntimeState) -> dict[str, Any] | None:
    ctx.parse_quality_low_threshold = settings.RETRIEVAL_PARSE_QUALITY_LOW_THRESHOLD
    ctx.parse_quality_low_threshold = min(1.0, max(0.0, ctx.parse_quality_low_threshold))

    ctx.parse_quality_alert_ratio = settings.RETRIEVAL_PARSE_QUALITY_ALERT_RATIO
    ctx.parse_quality_alert_ratio = min(1.0, max(0.0, ctx.parse_quality_alert_ratio))

    ctx.parse_quality_summary = _summarize_parse_quality_risk(
        ctx.docs,
        low_threshold=ctx.parse_quality_low_threshold,
        alert_ratio=ctx.parse_quality_alert_ratio,
    )
    ctx.parse_quality_gate_profile = str(settings.RETRIEVAL_PARSE_QUALITY_GATE_PROFILE).strip().lower() or "warn"
    if ctx.parse_quality_gate_profile not in {"off", "warn", "strict"}:
        ctx.parse_quality_gate_profile = "warn"
    ctx.parse_quality_gate_violation = ctx.parse_quality_summary["alert"]
    ctx.parse_quality_gate_blocked = bool(
        ctx.parse_quality_gate_profile == "strict" and ctx.parse_quality_gate_violation
    )
    ctx.parse_quality_gate_reason = "parse_quality_alert" if ctx.parse_quality_gate_violation else None
    parse_risk_hardcase_min_low_ratio = settings.RETRIEVAL_PARSE_RISK_HARDCASE_MIN_LOW_RATIO
    parse_risk_hardcase_min_low_ratio = min(1.0, max(0.0, parse_risk_hardcase_min_low_ratio))

    parse_risk_hardcase_min_considered = settings.RETRIEVAL_PARSE_RISK_HARDCASE_MIN_CONSIDERED
    parse_risk_hardcase_min_considered = max(1, parse_risk_hardcase_min_considered)

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
    ctx.metrics["retrieval_profile"] = ctx.profile_norm
    ctx.metrics["retrieval_profile_requested"] = (
        str(ctx.requested_retrieval_profile).strip().lower() if ctx.requested_retrieval_profile is not None else None
    )
    ctx.metrics["temporal_intent_enabled"] = bool(ctx.temporal_intent_enabled)
    ctx.metrics["temporal_intent_detected"] = bool(ctx.temporal_intent_meta.get("detected"))
    ctx.metrics["temporal_intent_reason_codes"] = list(ctx.temporal_intent_meta.get("reason_codes") or [])
    ctx.metrics["temporal_recency_rerank"] = (
        dict(ctx.temporal_recency_meta) if isinstance(ctx.temporal_recency_meta, dict) else None
    )
    ctx.metrics["retrieval_contract_mode"] = ctx.retrieval_contract_mode
    ctx.metrics["retrieval_contract_policy"] = dict(ctx.retrieval_contract_policy)
    ctx.metrics["retrieval_contract_deterministic_recall"] = bool(ctx.contract_deterministic_recall)
    ctx.metrics["retrieval_contract_must_recall_strict"] = bool(ctx.contract_must_recall_strict)
    ctx.metrics["contract_fail_reason_taxonomy"] = str(ctx.retrieval_contract_policy["contract_fail_reason_taxonomy"])
    ctx.metrics["must_recall_enabled"] = bool(ctx.must_recall_enabled)
    ctx.metrics["must_recall_requested"] = (
        bool(ctx.must_recall_requested) if ctx.must_recall_requested is not None else None
    )
    ctx.metrics["must_recall_expected_source_keys"] = list(ctx.must_recall_expected_source_keys)
    ctx.metrics["must_recall_required_anchor_fields"] = list(ctx.must_recall_required_anchor_fields)
    ctx.metrics["must_recall_auto_expected_source_keys_enabled"] = bool(
        ctx.must_recall_auto_expected_source_keys_enabled
    )
    ctx.metrics["must_recall_auto_expected_source_keys_applied"] = bool(
        ctx.must_recall_auto_expected_source_keys_applied
    )
    ctx.metrics["must_recall_auto_expected_source_keys"] = list(ctx.must_recall_auto_expected_source_keys)
    ctx.metrics["must_recall_auto_expected_source_keys_reason_codes"] = list(
        ctx.must_recall_auto_expected_source_keys_reason_codes
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
    ctx.metrics["must_recall_auto_required_anchor_fields"] = list(ctx.must_recall_auto_required_anchor_fields)
    ctx.metrics["must_recall_auto_required_anchor_fields_reason_codes"] = list(
        ctx.must_recall_auto_required_anchor_fields_reason_codes
    )
    ctx.metrics["must_recall_status"] = str(ctx.must_recall_status)
    ctx.metrics["must_recall_passed"] = bool(ctx.must_recall_passed)
    ctx.metrics["must_recall_missing_source_keys"] = ctx.missing_source_keys[:40]
    ctx.metrics["must_recall_anchor_missing_counts"] = dict(ctx.must_recall_anchor_eval["missing_counts"])
    ctx.metrics["must_recall_anchor_considered_citations"] = int(ctx.must_recall_anchor_eval["considered_citations"])
    ctx.metrics["must_recall_anchor_skipped_citations"] = int(ctx.must_recall_anchor_eval["skipped_citations"])
    ctx.metrics["must_recall_anchor_skipped_by_role"] = dict(ctx.must_recall_anchor_eval["skipped_by_role"])
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
    ctx.metrics["contextual_followup_reason_codes"] = list(ctx.contextual_followup_reason_codes)
    ctx.metrics["contextual_followup_selected_terms"] = list(ctx.contextual_followup_selected_terms)
    ctx.metrics["contextual_followup_query_hash"] = ctx.contextual_followup_query_hash
    ctx.metrics["contextual_followup_elapsed_sec"] = round(float(ctx.contextual_followup_elapsed or 0.0), 3)
    ctx.metrics["contextual_followup_error"] = ctx.contextual_followup_error
    ctx.metrics["iterative_pass_enabled"] = bool(ctx.contextual_followup_enabled)
    ctx.metrics["iterative_pass_max_hops"] = int(ctx.contextual_followup_max_hops)
    ctx.metrics["iterative_pass_latency_budget_ms"] = round(float(ctx.contextual_followup_latency_budget_ms), 3)
    ctx.metrics["iterative_pass_hops_attempted"] = len(
        [h for h in ctx.iterative_pass_hops if isinstance(h, dict) and bool(h.get("attempted"))]
    )
    ctx.metrics["iterative_pass_hops_used"] = len(
        [h for h in ctx.iterative_pass_hops if isinstance(h, dict) and bool(h.get("used"))]
    )
    ctx.metrics["iterative_pass_reason_codes"] = list(ctx.iterative_pass_reason_codes)[:16]
    ctx.metrics["iterative_pass_gap"] = (
        dict(ctx.iterative_pass_gap or {}) if isinstance(ctx.iterative_pass_gap, dict) else None
    )
    ctx.metrics["iterative_pass_hops"] = [h for h in list(ctx.iterative_pass_hops)[:5] if isinstance(h, dict)]
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
        f"{health_item['kind']}:{reason['channel'].strip() or 'unknown'}:{reason['error_type'].strip() or 'unknown'}"
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
        (item for item in ctx.channel_health_queries if item["kind"] == "main"),
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
    ctx.metrics["evidence_post_rerank_enabled"] = ctx.post_rerank_enabled
    ctx.metrics["evidence_post_rerank_used"] = ctx.post_rerank_used
    ctx.metrics["evidence_post_rerank_provider"] = ctx.post_rerank_provider
    ctx.metrics["evidence_post_rerank_candidates_n"] = ctx.post_rerank_candidates_n
    ctx.metrics["evidence_post_rerank_elapsed_sec"] = round(ctx.post_rerank_elapsed, 3)
    ctx.metrics["evidence_post_rerank_model_used"] = ctx.post_rerank_model_used
    ctx.metrics["evidence_post_rerank_error"] = ctx.post_rerank_error
    ctx.metrics["evidence_post_rerank_skip_reason"] = ctx.post_rerank_skip_reason
    ctx.metrics["evidence_post_rerank_cache_enabled"] = ctx.post_rerank_cache_enabled
    ctx.metrics["evidence_post_rerank_cache_backend"] = ctx.post_rerank_cache_backend
    ctx.metrics["evidence_post_rerank_cache_hits"] = ctx.post_rerank_cache_hits
    ctx.metrics["evidence_post_rerank_cache_misses"] = ctx.post_rerank_cache_misses
    ctx.metrics["evidence_post_rerank_pipeline_enabled"] = ctx.post_rerank_pipeline_enabled
    ctx.metrics["evidence_post_rerank_pipeline_used"] = ctx.post_rerank_pipeline_used
    ctx.metrics["evidence_post_rerank_pipeline_stages"] = ctx.post_rerank_pipeline_stages[:4]
    ctx.metrics["evidence_post_rerank_score_calibration_enabled"] = ctx.post_rerank_score_calibration_enabled
    ctx.metrics["evidence_post_rerank_score_calibration_alpha"] = round(ctx.post_rerank_score_calibration_alpha, 4)
    ctx.metrics["evidence_post_rerank_score_calibration_used"] = ctx.post_rerank_score_calibration_used
    ctx.metrics["evidence_post_rerank_score_calibration"] = dict(ctx.post_rerank_score_calibration_stats)

    ctx.metrics["query_rewrite_enabled"] = bool(ctx.rewrite_enabled)
    ctx.metrics["query_rewrite_strategy_id"] = ctx.rewrite_strategy_id
    ctx.metrics["query_rewrite_strategy_hash"] = ctx.rewrite_strategy_hash
    ctx.metrics["rewrite_used"] = bool(ctx.rewrite_used)
    ctx.metrics["rewrite_elapsed_sec"] = round(ctx.rewrite_elapsed, 3)
    ctx.metrics["rewrite_model_used"] = ctx.rewrite_model_used

    ctx.metrics["alias_enabled"] = bool(ctx.alias_enabled)
    ctx.metrics["alias_used"] = ctx.alias_used
    ctx.metrics["alias_count"] = len(ctx.alias_queries)
    ctx.metrics["alias_elapsed_sec"] = round(ctx.alias_elapsed, 3)
    ctx.metrics["alias_meta"] = ctx.alias_meta

    ctx.metrics["dict_enabled"] = bool(ctx.dict_meta.get("enabled"))
    ctx.metrics["dict_used"] = bool(ctx.dict_used)
    ctx.metrics["dict_count"] = len(ctx.dict_expansions)
    ctx.metrics["dict_elapsed_sec"] = round(ctx.dict_elapsed, 3)
    ctx.metrics["dict_meta"] = ctx.dict_meta

    ctx.metrics["kg_query_expansion_enabled"] = bool(ctx.kg_query_expansion_enabled)
    ctx.metrics["kg_query_expansion_used"] = ctx.kg_query_expansion_used
    ctx.metrics["kg_query_expansion_entities_total"] = ctx.kg_query_expansion_entities_total
    ctx.metrics["kg_query_expansion_entities_selected"] = ctx.kg_query_expansion_entities_selected
    ctx.metrics["kg_query_expansion_query_count"] = len(ctx.kg_query_expansion_queries)
    ctx.metrics["kg_query_expansion_elapsed_sec"] = round(ctx.kg_query_expansion_elapsed, 3)
    ctx.metrics["kg_query_expansion_error"] = ctx.kg_query_expansion_error
    ctx.metrics["kg_chunk_injection_enabled"] = bool(ctx.kg_chunk_injection_enabled)
    ctx.metrics["kg_chunk_injection_max_chunks"] = int(ctx.kg_chunk_injection_max_chunks)
    ctx.metrics["kg_chunks_injected"] = ctx.kg_chunks_injected
    ctx.metrics["kg_chunk_injection_error"] = ctx.kg_chunk_injection_error
    ctx.metrics["kg_chunk_boost_enabled"] = bool(ctx.kg_chunk_boost_meta.get("enabled"))
    ctx.metrics["kg_chunk_boost_weight"] = float(ctx.kg_chunk_boost_meta.get("weight") or 0.0)
    ctx.metrics["kg_chunk_boost_max_promoted"] = int(ctx.kg_chunk_boost_meta.get("max_promoted") or 0)
    ctx.metrics["kg_chunk_boost_eligible"] = int(ctx.kg_chunk_boost_meta.get("eligible") or 0)
    ctx.metrics["kg_chunk_boost_promoted"] = int(ctx.kg_chunk_boost_meta.get("promoted") or 0)
    ctx.metrics["kg_chunk_boost_top_changed"] = bool(ctx.kg_chunk_boost_meta.get("top_changed"))
    ctx.metrics["kg_chunk_boost_reason"] = ctx.kg_chunk_boost_meta.get("reason")
    ctx.metrics["metadata_exact_anchor_doc_ordering"] = dict(ctx.metadata_exact_anchor_doc_order_meta)

    ctx.metrics["multi_query_enabled"] = bool(ctx.mq_enabled)
    ctx.metrics["multi_query_used"] = bool(ctx.multi_query_used)
    ctx.metrics["multi_query_count"] = len(ctx.multi_queries)
    ctx.metrics["multi_query_elapsed_sec"] = round(ctx.multi_query_elapsed, 3)
    ctx.metrics["multi_query_model_used"] = ctx.multi_query_model_used
    ctx.metrics["multi_query_parse_ok"] = bool(ctx.multi_query_parse_meta.get("ok"))
    ctx.metrics["multi_query_parse_method"] = ctx.multi_query_parse_meta.get("method")
    ctx.metrics["multi_query_parse_error"] = ctx.multi_query_parse_meta.get("error")
    ctx.metrics["multi_query_diversify_enabled"] = ctx.mq_diversify_enabled
    ctx.metrics["multi_query_diversify_budget"] = ctx.mq_diversify_budget if ctx.mq_diversify_enabled else 0
    ctx.metrics["multi_query_diversify_used"] = ctx.mq_diversify_used
    ctx.metrics["multi_query_diversify_selected_mq"] = ctx.mq_diversify_selected_mq
    ctx.metrics["multi_query_diversify_selected_non_mq"] = ctx.mq_diversify_selected_non_mq
    ctx.metrics["multi_query_diversify_fill_from_fused"] = ctx.mq_diversify_fill_from_fused
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
    ctx.metrics["hierarchy_context_expansion_attempted"] = ctx.hierarchy_expand_attempted
    ctx.metrics["hierarchy_context_expansion_used"] = ctx.hierarchy_expand_used
    ctx.metrics["hierarchy_context_expansion_elapsed_sec"] = round(ctx.hierarchy_expand_elapsed, 3)
    ctx.metrics["hierarchy_context_expansion_error"] = ctx.hierarchy_expand_error
    ctx.metrics["hierarchy_context_expansion_meta"] = dict(ctx.hierarchy_expand_meta)

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
    ctx.metrics["decompose_chain_steps"] = ctx.decompose_chain_steps
    ctx.metrics["decompose_chain_elapsed_sec"] = round(ctx.decompose_chain_elapsed, 3)
    ctx.metrics["parse_quality"] = dict(ctx.parse_quality_summary)
    ctx.metrics["parse_quality_low_threshold"] = float(ctx.parse_quality_low_threshold)
    ctx.metrics["parse_quality_alert_ratio"] = float(ctx.parse_quality_alert_ratio)
    ctx.metrics["parse_quality_alert"] = bool(ctx.parse_quality_summary["alert"])
    ctx.metrics["parse_quality_low_ratio"] = float(ctx.parse_quality_summary["low_ratio"])
    ctx.metrics["parse_quality_considered"] = int(ctx.parse_quality_summary["considered"])
    ctx.metrics["parse_quality_recommendation"] = ctx.parse_quality_summary["recommendation"]
    ctx.metrics["parse_quality_gate_profile"] = str(ctx.parse_quality_gate_profile)
    ctx.metrics["parse_quality_gate_violation"] = bool(ctx.parse_quality_gate_violation)
    ctx.metrics["parse_quality_gate_blocked"] = bool(ctx.parse_quality_gate_blocked)
    ctx.metrics["parse_quality_gate_reason"] = ctx.parse_quality_gate_reason
    ctx.metrics["parse_risk"] = dict(ctx.parse_risk)
    ctx.metrics["parse_risk_level"] = str(ctx.parse_risk["level"])
    ctx.metrics["parse_risk_score"] = float(ctx.parse_risk["score"])
    ctx.metrics["parse_risk_reason"] = ctx.parse_risk["reason"]
    ctx.metrics["parse_risk_hardcase_eligible"] = bool(ctx.parse_risk["hardcase_eligible"])
    parse_repair_actions = ctx.parse_repair_actions_meta
    ctx.metrics["parse_repair_actions"] = dict(parse_repair_actions) if parse_repair_actions is not None else None
    ctx.metrics["parse_repair_actions_enabled"] = parse_repair_actions is not None
    ctx.metrics["parse_repair_actions_run_id"] = (
        parse_repair_actions.get("run_id") if parse_repair_actions is not None else None
    )
    return None
