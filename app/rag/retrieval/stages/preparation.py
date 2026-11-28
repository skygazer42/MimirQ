"""Prepare retrieval requests and expose planned query outcomes to the runtime."""

from typing import Any

from app.infrastructure.config import settings
from app.infrastructure.hashing import stable_hash
from app.infrastructure.model_policy import reject_retired_retrieval_options
from app.rag.policy.router_layers import build_router_layers
from app.rag.retrieval.configuration.profiles import normalize_retrieval_mode
from app.rag.retrieval.evidence.validity import requests_current_evidence
from app.rag.retrieval.planning.contracts import QueryPreparationOverrides, RetrievalRequest
from app.rag.retrieval.planning.options import (
    QUERY_PLANNING_OPTION_KEYS,
    parse_query_expansion_budget,
    resolve_query_preparation_request,
)
from app.rag.retrieval.planning.planner import prepare_query_plan
from app.rag.retrieval.recall.retriever import hybrid_retriever
from app.rag.retrieval.stages.state import RetrievalRuntimeState
from app.rag.runtime.query_models import EngineQueryModels
from app.services.retrieval.router_metrics import observe_router_layers


def _build_no_retrieval_response(
    state: dict[str, Any],
    *,
    question: str,
    no_retrieval_intent: dict[str, Any],
) -> dict[str, Any]:
    reject_retired_retrieval_options(state)
    requested_retrieval_mode = state.get("retrieval_mode", "hybrid") or "hybrid"
    requested_retrieval_profile = state.get("retrieval_profile")
    retrieval_mode = normalize_retrieval_mode(requested_retrieval_mode)
    profile_norm = requested_retrieval_profile.strip().lower() if requested_retrieval_profile is not None else None
    if not profile_norm:
        profile_norm = None
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
    router_layers = build_router_layers(query=question, intent_meta=dict(no_retrieval_intent), max_reason_codes=6)
    query_debug["router_layers"] = router_layers
    observe_router_layers(router_layers)
    retrieval_trace: dict[str, Any] = {
        "schema": "mimirq.retrieval_trace_pass.v1",
        "query_for_retrieval_hash": stable_hash(question),
        "requested_retrieval_mode": requested_retrieval_mode,
        "retrieval_mode": retrieval_mode,
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


def _build_retrieval_request(state: dict[str, Any], *, question: str, history_text: str) -> RetrievalRequest:
    reject_retired_retrieval_options(state)
    rewrite_temperature = state.get("query_rewrite_temperature")
    rewrite_max_chars = state.get("query_rewrite_max_chars")
    overrides = QueryPreparationOverrides(
        enable_rewrite=None if state.get("enable_query_rewrite") is None else bool(state["enable_query_rewrite"]),
        rewrite_strategy=state.get("query_rewrite_strategy"),
        rewrite_temperature=None if rewrite_temperature is None else float(rewrite_temperature),
        rewrite_max_chars=None if rewrite_max_chars is None else int(rewrite_max_chars),
        industry_enabled=(
            None if state.get("industry_rules_enabled") is None else bool(state["industry_rules_enabled"])
        ),
        industry_rulesets=state.get("industry_rules_rulesets"),
    )
    preparation = resolve_query_preparation_request(
        question,
        history_text,
        overrides,
        temporal_enabled=bool(settings.RAG_TEMPORAL_INTENT_ENABLED),
    )
    options = {key: state[key] for key in QUERY_PLANNING_OPTION_KEYS if key in state}
    return RetrievalRequest(preparation, options, parse_query_expansion_budget(options))


def _run_retrieval_bootstrap_phase(ctx: RetrievalRuntimeState) -> dict[str, Any] | None:
    from app.rag.runtime.engine import get_rag_engine

    engine: Any | None = None

    def llm_engine() -> Any:
        nonlocal engine
        if engine is None:
            engine = get_rag_engine()
        return engine

    request = _build_retrieval_request(ctx.state, question=ctx.question, history_text=ctx.history_text)
    ctx.query_plan = prepare_query_plan(request, models=EngineQueryModels(llm_engine))

    plan = ctx.query_plan
    prepared, routing = plan.prepared, plan.routing
    evidence, normalization = routing.evidence_contract, routing.normalization
    rewrite = prepared.rewrite
    rewrite_configuration = rewrite.configuration
    ctx.rewrite_enabled = rewrite.enabled
    ctx.rewrite_elapsed = rewrite.elapsed_sec
    ctx.rewrite_model_used = rewrite.model_used
    ctx.rewrite_strategy_id = rewrite.strategy_id
    ctx.rewrite_strategy_hash = rewrite.strategy_hash
    ctx.rewrite_temperature = rewrite_configuration.temperature if rewrite_configuration else None
    ctx.rewrite_max_chars = rewrite_configuration.max_chars if rewrite_configuration else None
    ctx.industry_rules_meta = prepared.industry.metadata
    ctx.temporal_intent_enabled = prepared.temporal.enabled
    ctx.temporal_intent_meta = prepared.temporal.metadata
    ctx.temporal_recency_meta = {"enabled": False, "used": False, "reason": "not_run"}
    ctx.kg_result_cached = plan.kg.response

    for key, value in evidence.items():
        if key not in {"retrieval_contract_policy", "hierarchy_recall_enabled"}:
            setattr(ctx, key, value)
    ctx.request_retrieval_mode = normalization.request_retrieval_mode
    ctx.retrieval_mode_routed = normalization.retrieval_mode_routed
    ctx.retrieval_contract_mode = normalization.retrieval_contract_mode
    ctx.contract_deterministic_recall = normalization.contract_deterministic_recall
    ctx.contract_must_recall_strict = bool(evidence["contract_must_recall_strict"])
    ctx.profile_norm = normalization.profile_norm
    ctx.retrieval_profile = normalization.profile_norm
    ctx.intent_router_meta = routing.intent_metadata
    ctx.adaptive_router_meta = routing.adaptive_metadata
    ctx.channel_budget_policy_meta = routing.channel_metadata
    ctx.hierarchy_family_collapse = normalization.hierarchy.family_collapse
    ctx.hierarchy_family_aggregation = normalization.hierarchy.family_aggregation
    ctx.hierarchy_tree_dedup = normalization.hierarchy.tree_dedup
    ctx.hierarchy_parent_depth = normalization.hierarchy.parent_depth
    ctx.hierarchy_sibling_window = normalization.hierarchy.sibling_window
    ctx.hierarchy_overfetch_factor = normalization.hierarchy.overfetch_factor
    ctx.retriever_update = dict(plan.retriever_options, current_evidence_only=requests_current_evidence(ctx.question))
    ctx.retriever = hybrid_retriever.model_copy(update=ctx.retriever_update)
    ctx.retrieval_mode = ctx.retriever_update["retrieval_mode"]
    return None


def _run_retrieval_alias_dictionary_phase(ctx: RetrievalRuntimeState) -> dict[str, Any] | None:
    deterministic = ctx.query_plan.deterministic
    ctx.alias_elapsed = deterministic.alias.elapsed_sec
    ctx.alias_used = bool(deterministic.alias.queries)
    ctx.alias_meta = deterministic.alias.metadata
    ctx.alias_enabled = ctx.query_plan.alias_settings.enabled
    ctx.dict_elapsed = deterministic.dictionary.elapsed_sec
    ctx.dict_used = bool(deterministic.dictionary.expansions)
    ctx.dict_meta = deterministic.dictionary.metadata
    ctx.dict_expansions = list(deterministic.dictionary.expansions)
    return None


def _run_retrieval_kg_query_expansion_phase(ctx: RetrievalRuntimeState) -> dict[str, Any] | None:
    expansion = ctx.query_plan.kg
    ctx.kg_result_cached = expansion.response
    ctx.kg_query_expansion_enabled = expansion.enabled
    ctx.kg_query_expansion_used = expansion.used
    ctx.kg_query_expansion_elapsed = expansion.elapsed_sec
    ctx.kg_query_expansion_entities_total = expansion.entities_total
    ctx.kg_query_expansion_entities_selected = expansion.entities_selected
    ctx.kg_query_expansion_queries = list(expansion.queries)
    ctx.kg_query_expansion_entity_names = list(expansion.entity_names)
    ctx.kg_query_expansion_error = str(expansion.failure)[:200] if expansion.failure is not None else None
    return None


def _run_retrieval_multi_query_phase(ctx: RetrievalRuntimeState) -> dict[str, Any] | None:
    multi = ctx.query_plan.models.multi_query
    multi_settings = ctx.query_plan.model_settings.multi_query
    experiment = multi_settings.experiment
    ctx.multi_query_ab_test_key = experiment.key
    ctx.multi_query_ab_variant = experiment.variant
    ctx.multi_query_ab_seed = experiment.seed
    ctx.multi_query_ab_forced = experiment.forced
    ctx.mq_enabled = multi_settings.enabled
    ctx.mq_n = multi_settings.count
    ctx.mq_temp = multi_settings.temperature
    ctx.mq_max_chars = multi_settings.max_chars
    ctx.multi_query_elapsed = multi.elapsed_sec
    ctx.multi_query_used = multi.used
    ctx.multi_query_model_used = multi.model_used
    ctx.multi_query_parse_meta = multi.parse_metadata
    return None


def _run_retrieval_hyde_phase(ctx: RetrievalRuntimeState) -> dict[str, Any] | None:
    hyde = ctx.query_plan.models.hyde
    ctx.hyde_enabled = ctx.query_plan.model_settings.hyde.enabled
    ctx.hyde_text = hyde.text
    ctx.hyde_elapsed = hyde.elapsed_sec
    ctx.hyde_model_used = hyde.model_used
    ctx.hyde_used = hyde.used
    return None


def _run_retrieval_step_back_phase(ctx: RetrievalRuntimeState) -> dict[str, Any] | None:
    step_back = ctx.query_plan.models.step_back
    step_back_settings = ctx.query_plan.model_settings.step_back
    ctx.step_back_enabled = step_back_settings.enabled
    ctx.step_back_max_chars = step_back_settings.max_chars
    ctx.step_back_temp = step_back_settings.temperature
    ctx.step_back_output_max = step_back_settings.output_max_chars
    ctx.step_back_query = step_back.text
    ctx.step_back_elapsed = step_back.elapsed_sec
    ctx.step_back_model_used = step_back.model_used
    ctx.step_back_parse_meta = step_back.parse_metadata
    ctx.step_back_used = step_back.used
    return None


def _run_retrieval_decomposition_variants_phase(ctx: RetrievalRuntimeState) -> dict[str, Any] | None:
    decomposition = ctx.query_plan.models.decomposition
    ctx.decompose_enabled = ctx.query_plan.model_settings.decomposition.enabled
    ctx.decompose_elapsed = decomposition.elapsed_sec
    ctx.decompose_used = decomposition.used
    ctx.decompose_model_used = decomposition.model_used
    ctx.decompose_parse_meta = decomposition.parse_metadata
    ctx.sub_questions = list(decomposition.queries)
    ctx.decompose_chain_enabled = bool(settings.RAG_DECOMPOSITION_CHAIN_ENABLED)
    ctx.decompose_chain_requested = bool(ctx.decompose_chain_enabled and ctx.sub_questions)
    ctx.decompose_chain_used = False
    ctx.decompose_chain_steps = 0
    ctx.decompose_chain_elapsed = 0.0
    ctx.decompose_chain_queries: list[str] = []
    ctx.clause_fastlane_queries = list(ctx.query_plan.clause_queries)
    ctx.lightweight_subqueries = list(ctx.query_plan.lightweight_queries)
    variant_stage = ctx.query_plan.variant_stage
    ctx.query_expansion_budget_meta = dict(variant_stage.query_expansion_budget_meta)
    ctx.query_expansion_budget_max_queries = variant_stage.query_expansion_budget_max_queries
    ctx.query_expansion_budget_max_candidates = variant_stage.query_expansion_budget_max_candidates
    ctx.query_expansion_budget_token_budget = variant_stage.query_expansion_budget_token_budget
    ctx.query_expansion_budget_latency_ms = variant_stage.query_expansion_budget_latency_ms
    return None
