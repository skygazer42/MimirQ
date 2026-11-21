"""Build bounded query diagnostics and the retrieval trace."""

from typing import Any

from app.query.normalize import normalize_query
from app.rag.policy.router_layers import build_router_layers
from app.rag.retrieval.stages.state import RetrievalRuntimeState
from app.rag.tracing.retrieval import build_retrieval_trace
from app.services.retrieval.router_metrics import observe_router_layers


def _populate_query_normalization_debug(ctx: RetrievalRuntimeState) -> None:
    normalized = normalize_query(ctx.query_for_retrieval)
    ctx.query_debug["normalized"] = normalized.normalized_text
    ctx.query_debug["applied_rules"] = normalized.applied_rules[:20]
    # Sanitized per-query diagnostics contain lengths, never the normalized text.
    main_debug = next(
        (item["retriever_debug"] for item in ctx.retrieval_per_query if item["kind"] == "main"),
        None,
    )
    if main_debug is not None and "channels" in main_debug:
        ctx.query_debug["channels"] = main_debug["channels"]


def _dictionary_debug_expansions(expansions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"kind": "dict", **expansion} for expansion in expansions]


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
    by_role: dict[str, int] = {}
    for citation in ctx.citations:
        role = (citation.get("retrieval_role") or "main").strip() or "main"
        by_role[role] = by_role.get(role, 0) + 1
    return [
        {"retrieval_role": role, "citations": count}
        for role, count in sorted(by_role.items(), key=lambda item: (-item[1], item[0]))
    ]


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
        "steps": ctx.decompose_chain_steps,
        "queries": ctx.decompose_chain_queries[:5],
        "elapsed_sec": round(ctx.decompose_chain_elapsed, 3),
    }
    if ctx.kg_query_expansion_entity_names:
        ctx.query_debug["kg_entities"] = ctx.kg_query_expansion_entity_names[:10]
    ctx.query_debug["contributions"] = _query_debug_contributions(ctx)

    ctx.query_debug["query_for_retrieval"] = ctx.query_for_retrieval
    ctx.query_debug["rewrite_used"] = bool(ctx.rewrite_used)
    ctx.query_debug["retrieval_profile"] = ctx.profile_norm
    ctx.query_debug["retrieval_profile_requested"] = (
        str(ctx.requested_retrieval_profile).strip().lower() if ctx.requested_retrieval_profile is not None else None
    )
    ctx.router_layers = build_router_layers(
        query=ctx.query_for_retrieval,
        entity_key=ctx.state.get("entity_key"),
        partition_keys=(
            list(ctx.state.get("partition_keys") or []) if isinstance(ctx.state.get("partition_keys"), list) else None
        ),
        entity_candidates=(
            list(ctx.state.get("entity_candidates") or [])
            if isinstance(ctx.state.get("entity_candidates"), list)
            else None
        ),
        intent_meta=(ctx.intent_router_meta if isinstance(ctx.intent_router_meta, dict) else None),
        max_reason_codes=6,
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
        "context_expansion_attempted": ctx.hierarchy_expand_attempted,
        "context_expansion_used": ctx.hierarchy_expand_used,
        "context_expansion_elapsed_sec": round(ctx.hierarchy_expand_elapsed, 3),
        "context_expansion_error": ctx.hierarchy_expand_error,
        "context_expansion_meta": dict(ctx.hierarchy_expand_meta),
    }
    ctx.query_debug["contextual_followup"] = {
        "enabled": bool(ctx.contextual_followup_enabled),
        "attempted": bool(ctx.contextual_followup_attempted),
        "used": bool(ctx.contextual_followup_used),
        "mode": str(ctx.contextual_followup_mode),
        "top_k": int(ctx.contextual_followup_top_k),
        "added_docs": int(ctx.contextual_followup_added_docs),
        "added_citations": int(ctx.contextual_followup_added_citations),
        "reason_codes": list(ctx.contextual_followup_reason_codes),
        "selected_terms": list(ctx.contextual_followup_selected_terms),
        "query": (
            str(ctx.contextual_followup_followup_query)[:220] if ctx.contextual_followup_followup_query else None
        ),
        "error": ctx.contextual_followup_error,
    }
    ctx.query_debug["iterative_pass"] = {
        "enabled": bool(ctx.contextual_followup_enabled),
        "max_hops": int(ctx.contextual_followup_max_hops),
        "latency_budget_ms": round(float(ctx.contextual_followup_latency_budget_ms), 3),
        "hops_attempted": len([h for h in ctx.iterative_pass_hops if isinstance(h, dict) and bool(h.get("attempted"))]),
        "hops_used": len([h for h in ctx.iterative_pass_hops if isinstance(h, dict) and bool(h.get("used"))]),
        "reason_codes": list(ctx.iterative_pass_reason_codes)[:16],
        "gap": (dict(ctx.iterative_pass_gap or {}) if isinstance(ctx.iterative_pass_gap, dict) else None),
        "hops": [h for h in list(ctx.iterative_pass_hops)[:5] if isinstance(h, dict)],
    }
    ctx.query_debug["parse_quality"] = {
        "considered": int(ctx.parse_quality_summary["considered"]),
        "low_ratio": float(ctx.parse_quality_summary["low_ratio"]),
        "alert": bool(ctx.parse_quality_summary["alert"]),
        "recommendation": ctx.parse_quality_summary["recommendation"],
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
    ctx.query_debug["retrieval_degraded_reasons"] = list(ctx.retrieval_degraded_reason_codes)
    ctx.query_debug["channel_health"] = dict(ctx.retrieval_channel_health)
    ctx.query_debug["fallback_reason"] = ctx.retrieval_fallback_reason
    ctx.query_debug["multi_query_ab"] = {
        "test_key": ctx.multi_query_ab_test_key,
        "variant": ctx.multi_query_ab_variant,
        "seed": ctx.multi_query_ab_seed,
        "forced_enable": bool(ctx.multi_query_ab_forced),
    }
    ctx.query_debug["retrieval_contract"] = {
        "mode": ctx.retrieval_contract_mode,
        "deterministic_recall": bool(ctx.contract_deterministic_recall),
        "must_recall_strict": bool(ctx.contract_must_recall_strict),
        "must_recall_enabled": bool(ctx.must_recall_enabled),
        "must_recall_status": str(ctx.must_recall_status),
        "must_recall_passed": bool(ctx.must_recall_passed),
        "must_recall_expected_source_keys": list(ctx.must_recall_expected_source_keys),
        "must_recall_missing_source_keys": list(ctx.missing_source_keys)[:20],
        "must_recall_required_anchor_fields": list(ctx.must_recall_required_anchor_fields),
        "must_recall_auto_expected_source_keys": {
            "enabled": bool(ctx.must_recall_auto_expected_source_keys_enabled),
            "applied": bool(ctx.must_recall_auto_expected_source_keys_applied),
            "keys": list(ctx.must_recall_auto_expected_source_keys),
            "reason_codes": list(ctx.must_recall_auto_expected_source_keys_reason_codes),
            "confidence": str(ctx.must_recall_auto_expected_source_keys_confidence or "none"),
        },
        "must_recall_auto_required_anchor_fields": {
            "enabled": bool(ctx.must_recall_auto_required_anchor_fields_enabled),
            "applied": bool(ctx.must_recall_auto_required_anchor_fields_applied),
            "fields": list(ctx.must_recall_auto_required_anchor_fields),
            "reason_codes": list(ctx.must_recall_auto_required_anchor_fields_reason_codes),
        },
        "must_recall_anchor_missing_counts": dict(ctx.must_recall_anchor_eval["missing_counts"]),
        "must_recall_fail_reasons": list(ctx.must_recall_fail_reasons)[:12],
        "contract_fail_reason_taxonomy": str(ctx.retrieval_contract_policy["contract_fail_reason_taxonomy"]),
        "second_pass": dict(ctx.must_recall_second_pass_payload),
        "must_recall_proof": dict(ctx.must_recall_proof),
    }
    if ctx.empty_diag:
        ctx.query_debug["empty_retrieval"] = ctx.empty_diag
    return None


def _run_retrieval_retrieval_trace_phase(ctx: RetrievalRuntimeState) -> dict[str, Any] | None:
    ctx.retrieval_trace = build_retrieval_trace(ctx)
    observe_router_layers(ctx.router_layers)
    return None
