"""Setup and routing phases for standard RAG streaming."""

import time
from collections.abc import AsyncGenerator
from typing import Any
from uuid import UUID

from app.core.config import settings
from app.rag.engine_support.query_model_calls import EngineQueryModels
from app.rag.engine_support.standard_stream_state import (
    StandardStreamState,
    StreamOperation,
)
from app.rag.retrieval.orchestration.query_contracts import QueryPreparationOverrides, SparseQuerySettings
from app.rag.retrieval.orchestration.query_options import QUERY_PLANNING_OPTION_KEYS, resolve_query_preparation_request
from app.rag.retrieval.orchestration.query_planning import prepare_query_async, resolve_sparse_selection
from app.rag.retrieval.orchestration.query_routing import resolve_stream_query_routing


async def agentic_phase(runtime: StandardStreamState) -> AsyncGenerator[dict[str, Any], None]:
    if (
        bool(getattr(settings, "RAG_AGENTIC_MODE_ENABLED", False))
        and runtime.data.complexity_score >= runtime.data.agentic_threshold
    ):
        runtime.data.runner = runtime.module.get_agentic_runner(engine=runtime.engine)
        async for runtime.data.event in runtime.data.runner.stream(
            question=runtime.data.question,
            history=runtime.data.history,
            conversation_id=runtime.data.conversation_id,
            document_ids=runtime.data.document_ids,
            dataset_ids=runtime.data.dataset_ids,
            tenant_id=runtime.data.tenant_id,
            account_id=runtime.data.account_id,
            dataset_id=runtime.data.dataset_id,
            top_k=runtime.data.top_k,
            score_threshold=runtime.data.score_threshold,
            retrieval_mode=runtime.data.retrieval_mode,
            retrieval_profile=runtime.data.retrieval_profile,
            retrieval_contract_mode=runtime.data.retrieval_contract_mode,
            must_recall=runtime.data.must_recall,
            must_recall_expected_source_keys=runtime.data.must_recall_expected_source_keys,
            must_recall_required_anchor_fields=runtime.data.must_recall_required_anchor_fields,
            intent_router=runtime.data.intent_router,
            intent_router_policy=runtime.data.intent_router_policy,
            industry_rules_enabled=runtime.data.industry_rules_enabled,
            industry_rules_rulesets=runtime.data.industry_rules_rulesets,
            enable_query_alias_expansion=runtime.data.enable_query_alias_expansion,
            query_aliases=runtime.data.query_aliases,
            query_alias_max_queries=runtime.data.query_alias_max_queries,
            enable_multi_query=runtime.data.enable_multi_query,
            multi_query_count=runtime.data.multi_query_count,
            multi_query_temperature=runtime.data.multi_query_temperature,
            multi_query_max_chars=runtime.data.multi_query_max_chars,
            enable_hierarchy_recall=runtime.data.enable_hierarchy_recall,
            hierarchy_family_collapse=runtime.data.hierarchy_family_collapse,
            hierarchy_family_aggregation=runtime.data.hierarchy_family_aggregation,
            hierarchy_tree_dedup=runtime.data.hierarchy_tree_dedup,
            hierarchy_parent_depth=runtime.data.hierarchy_parent_depth,
            hierarchy_sibling_window=runtime.data.hierarchy_sibling_window,
            hierarchy_overfetch_factor=runtime.data.hierarchy_overfetch_factor,
            alpha=runtime.data.alpha,
            fusion_strategy=runtime.data.fusion_strategy,
            fusion_budgets=runtime.data.fusion_budgets,
            fusion_min_scores=runtime.data.fusion_min_scores,
            fusion_weights=runtime.data.fusion_weights,
            retrieval_overfetch_multiplier=runtime.data.retrieval_overfetch_multiplier,
            retrieval_overfetch_max_k=runtime.data.retrieval_overfetch_max_k,
            sparse_retrieval_enabled=runtime.data.sparse_retrieval_enabled,
            sparse_retrieval_provider=runtime.data.sparse_retrieval_provider,
            enable_weight_rerank=runtime.data.enable_weight_rerank,
            vector_weight=runtime.data.vector_weight,
            keyword_weight=runtime.data.keyword_weight,
            mmr_lambda=runtime.data.mmr_lambda,
            enable_reranker=runtime.data.enable_reranker,
            reranker_provider=runtime.data.reranker_provider,
            reranker_top_n=runtime.data.reranker_top_n,
            metadata_filter=runtime.data.metadata_filter,
            structured_output=runtime.data.structured_output,
            structured_preset=runtime.data.structured_preset,
            visible_evidence_only=runtime.data.visible_evidence_only,
            prompt_template_id=runtime.data.prompt_template_id,
            prompt_template_key=runtime.data.prompt_template_key,
            prompt_ab_experiment_key=runtime.data.prompt_ab_experiment_key,
            ab_user_key=runtime.data.ab_user_key,
            request_id=runtime.data.request_id,
            db=runtime.data.db,
        ):
            yield runtime.data.event
        runtime.finished = True
        return


async def select_model_and_prompt(runtime: StandardStreamState) -> AsyncGenerator[dict[str, Any], None]:
    runtime.data.llm, runtime.data.model_route, runtime.data.routing_reason = runtime.engine._select_llm(
        runtime.data.question, runtime.data.history
    )
    runtime.data.llm, runtime.data.request_llm_meta = runtime.engine._maybe_override_llm_for_request(
        llm=runtime.data.llm,
        model_route=runtime.data.model_route,
        structured_output=bool(runtime.data.structured_output),
    )
    runtime.data.base_llm_model_name = getattr(runtime.data.llm, "model_name", None) or getattr(
        runtime.data.llm, "model", None
    )
    if runtime.data.generation_max_tokens > 0:
        runtime.data.llm = runtime.data.llm.bind(max_tokens=runtime.data.generation_max_tokens)
    if runtime.data.request_llm_meta.get("structured_temperature_override_applied"):
        structured_temperature = runtime.data.request_llm_meta.get("structured_temperature")
        runtime.data.routing_reason = f"{runtime.data.routing_reason}; structured_temperature={structured_temperature}"

    # Load prompt template (id / key latest / A/B experiment)
    runtime.data.current_prompt_template = runtime.engine.prompt_template
    runtime.data.selected_prompt_template_id: UUID | None = None
    runtime.data.selected_prompt_template_key: str | None = None
    runtime.data.selected_prompt_ab_experiment_key: str | None = None
    runtime.data.selected_prompt_ab_variant: str | None = None

    if (
        runtime.data.db
        and runtime.data.tenant_id
        and (
            runtime.data.prompt_template_id or runtime.data.prompt_template_key or runtime.data.prompt_ab_experiment_key
        )
    ):
        runtime.data.chosen = runtime.module.resolve_prompt_template(
            db=runtime.data.db,
            tenant_id=runtime.data.tenant_id,
            prompt_template_id=runtime.data.prompt_template_id,
            template_key=runtime.data.prompt_template_key,
            ab_experiment_key=runtime.data.prompt_ab_experiment_key,
            ab_user_key=runtime.data.ab_user_key,
        )
        if runtime.data.chosen:
            runtime.data.current_prompt_template = runtime.module.ChatPromptTemplate.from_template(
                runtime.data.chosen.content
            )
            runtime.data.chosen.usage_count += 1
            runtime.data.db.commit()
            runtime.data.selected_prompt_template_id = runtime.data.chosen.id
            runtime.data.selected_prompt_template_key = getattr(runtime.data.chosen, "template_key", None)
            runtime.data.selected_prompt_ab_experiment_key = getattr(runtime.data.chosen, "ab_experiment_key", None)
            runtime.data.selected_prompt_ab_variant = getattr(runtime.data.chosen, "ab_variant", None)

    runtime.data.chain = runtime.data.current_prompt_template | runtime.data.llm | runtime.module.StrOutputParser()

    runtime.data.format_instructions = ""
    if runtime.data.structured_output:
        runtime.data.format_instructions = runtime.module.build_structured_output_instructions(
            runtime.data.structured_preset
        )

    yield {
        "type": "route",
        "data": {
            "model_used": getattr(runtime.data.llm, "model_name", None) or getattr(runtime.data.llm, "model", None),
            "route": runtime.data.model_route,
            "reason": runtime.data.routing_reason,
            "structured_temperature": runtime.data.request_llm_meta.get("structured_temperature"),
            "structured_temperature_override_applied": bool(
                runtime.data.request_llm_meta.get("structured_temperature_override_applied")
            ),
            "prompt_template_id": str(runtime.data.selected_prompt_template_id)
            if runtime.data.selected_prompt_template_id
            else None,
            "prompt_template_key": runtime.data.selected_prompt_template_key,
            "prompt_ab_experiment_key": runtime.data.selected_prompt_ab_experiment_key,
            "prompt_ab_variant": runtime.data.selected_prompt_ab_variant,
        },
    }

    # Chat history (for prompt + optional query rewrite).
    runtime.data.history_text = runtime.module.format_history_text(
        runtime.data.history,
        window=settings.CHAT_HISTORY_WINDOW,
    )

    runtime.data.metadata_filter = runtime.engine._apply_active_pipeline_metadata_filter(
        db=runtime.data.db,
        tenant_id=runtime.data.tenant_id,
        document_ids=runtime.data.document_ids,
        metadata_filter=runtime.data.metadata_filter,
    )

    runtime.module._release_request_session(runtime.data.db)

    runtime.data.t_all_start = time.time()
    runtime.data.temporal_intent_enabled = bool(getattr(settings, "RAG_TEMPORAL_INTENT_ENABLED", False))
    runtime.data.temporal_intent_meta: dict[str, Any] = {"detected": False, "reason_codes": []}
    runtime.data.temporal_recency_meta: dict[str, Any] = {"enabled": False, "used": False, "reason": "not_run"}
    runtime.data.query_for_retrieval = runtime.data.question
    runtime.data.rewrite_elapsed = 0.0
    runtime.data.rewrite_used = False
    runtime.data.rewrite_model_used = None
    runtime.data.rewrite_strategy_id: str | None = None
    runtime.data.rewrite_strategy_hash: str | None = None
    runtime.data.rewrite_temperature: float | None = None
    runtime.data.rewrite_max_chars: int | None = None

    runtime.data.rewrite_enabled = bool(settings.ENABLE_QUERY_REWRITE)


async def rewrite_and_apply_industry_rules(runtime: StandardStreamState) -> AsyncGenerator[dict[str, Any], None]:
    request = resolve_query_preparation_request(
        runtime.data.question,
        runtime.data.history_text,
        QueryPreparationOverrides(
            sparse_enabled=runtime.data.sparse_retrieval_enabled,
            sparse_provider=runtime.data.sparse_retrieval_provider,
            industry_enabled=runtime.data.industry_rules_enabled,
            industry_rulesets=runtime.data.industry_rules_rulesets,
        ),
        temporal_enabled=bool(getattr(settings, "RAG_TEMPORAL_INTENT_ENABLED", False)),
    )
    prepared = await prepare_query_async(
        request,
        models=EngineQueryModels(lambda: runtime.engine, selected_model=runtime.data.llm),
    )
    runtime.data.prepared_query_outcome = prepared
    runtime.data.query_for_retrieval = prepared.query
    runtime.data.rewrite_enabled = prepared.rewrite.enabled
    runtime.data.rewrite_elapsed = prepared.rewrite.elapsed_sec
    runtime.data.rewrite_used = prepared.rewrite.used
    runtime.data.rewrite_model_used = prepared.rewrite.model_used
    runtime.data.rewrite_strategy_id = prepared.rewrite.strategy_id
    runtime.data.rewrite_strategy_hash = prepared.rewrite.strategy_hash
    configuration = prepared.rewrite.configuration
    runtime.data.rewrite_temperature = configuration.temperature if configuration is not None else None
    runtime.data.rewrite_max_chars = configuration.max_chars if configuration is not None else None
    runtime.data.sparse_retrieval_enabled = prepared.sparse.enabled
    runtime.data.sparse_retrieval_provider = prepared.sparse.provider
    runtime.data.industry_rules_enabled_effective = bool(prepared.industry.metadata.get("enabled"))
    runtime.data.industry_rules_meta = dict(prepared.industry.metadata)
    runtime.data.temporal_intent_enabled = prepared.temporal.enabled
    runtime.data.temporal_intent_meta = dict(prepared.temporal.metadata)
    runtime.data.temporal_recency_meta = {"enabled": False, "used": False, "reason": "not_run"}

    if prepared.rewrite.attempted:
        yield {
            "type": "rewrite",
            "data": {
                "original": runtime.data.question,
                "rewritten": runtime.data.query_for_retrieval,
                "used": runtime.data.rewrite_used,
                "elapsed_sec": round(runtime.data.rewrite_elapsed, 3),
                "model_used": runtime.data.rewrite_model_used,
                "strategy_id": runtime.data.rewrite_strategy_id,
                "strategy_hash": runtime.data.rewrite_strategy_hash,
            },
        }

    # Step 0.2: Multi-modal query router (deterministic, no LLM).
    #
    # This chooses a high-level modality so we can:
    # - run TAG/table injection only when the query looks tabular
    # - run CLIP image retrieval only when the query asks for figures/diagrams/screenshots
    runtime.data.multimodal_modality = "text"
    runtime.data.multimodal_reasons: list[str] = ["not_run"]


async def classify_modality_and_contract(runtime: StandardStreamState) -> None:
    try:
        from app.rag.policy.modality_router import classify_query_modality

        runtime.data.multimodal_modality, runtime.data.multimodal_reasons = classify_query_modality(
            runtime.data.query_for_retrieval
        )
    except Exception as exc:  # noqa: BLE001
        runtime.data.multimodal_modality = "text"
        runtime.data.multimodal_reasons = [f"router_exception:{str(exc)[:80]}"]


async def route_query(runtime: StandardStreamState) -> None:
    prepared = getattr(runtime.data, "prepared_query_outcome", None)
    if prepared is not None:
        sparse = prepared.sparse
    else:
        sparse = resolve_sparse_selection(
            SparseQuerySettings(
                bool(
                    settings.SPARSE_RETRIEVAL_ENABLED
                    if runtime.data.sparse_retrieval_enabled is None
                    else runtime.data.sparse_retrieval_enabled
                ),
                str(runtime.data.sparse_retrieval_provider or settings.SPARSE_RETRIEVAL_PROVIDER),
            )
        )

    options = {key: getattr(runtime.data, key) for key in QUERY_PLANNING_OPTION_KEYS if hasattr(runtime.data, key)}
    complexity_overrides = runtime.engine._route_retrieval_params(runtime.data.complexity_score)
    decision = resolve_stream_query_routing(
        runtime.data.query_for_retrieval,
        options=options,
        sparse=sparse,
        complexity_overrides=complexity_overrides,
    )
    routing = decision.routing
    normalization = routing.normalization
    effective_options = routing.effective_options
    retriever_update = normalization.retriever_update

    runtime.data.query_routing_outcome = routing
    runtime.data.recall_bucket = decision.recall_bucket
    runtime.data.adaptive_retrieval_overrides = dict(decision.complexity_overrides)
    runtime.data.adaptive_retrieval_used = bool(decision.complexity_overrides)
    runtime.data.intent_router_meta = dict(routing.intent_metadata)
    runtime.data.intent_router_enabled = bool(runtime.data.intent_router_meta.get("enabled"))
    runtime.data.adaptive_router_meta = dict(routing.adaptive_metadata)
    runtime.data.channel_budget_policy_meta = dict(routing.channel_metadata)

    for key, value in routing.evidence_contract.items():
        setattr(runtime.data, key, value)
    for key, value in effective_options.items():
        if key in QUERY_PLANNING_OPTION_KEYS:
            setattr(runtime.data, key, value)

    runtime.data.requested_retrieval_mode = routing.evidence_contract["requested_retrieval_mode"]
    runtime.data.requested_retrieval_profile = routing.evidence_contract["requested_retrieval_profile"]
    runtime.data.mode_req = runtime.data.requested_retrieval_mode
    runtime.data.profile_req = runtime.data.requested_retrieval_profile
    runtime.data.mode_auto = str(runtime.data.requested_retrieval_mode or "").strip().lower() == "auto"
    runtime.data.retrieval_mode_routed = normalization.retrieval_mode_routed
    runtime.data.retrieval_contract_policy = normalization.retrieval_contract_policy
    runtime.data.retrieval_contract_mode_effective = normalization.retrieval_contract_mode
    runtime.data.contract_req = effective_options.get("retrieval_contract_mode") or settings.RETRIEVAL_CONTRACT_MODE
    runtime.data.profile_applied = normalization.profile_applied
    runtime.data.profile_norm = normalization.profile_norm or ""
    runtime.data.retrieval_profile = normalization.profile_norm
    runtime.data.retriever_update = dict(retriever_update)
    runtime.data.mode_used = str(retriever_update["retrieval_mode"] or "hybrid")
    runtime.data.mode_norm = runtime.data.mode_used.lower().strip()
    runtime.data.top_k = int(retriever_update["k"])
    runtime.data.score_threshold = float(retriever_update["score_threshold"])
    runtime.data.score_threshold_used = runtime.data.score_threshold
    runtime.data.alpha_val = float(retriever_update["alpha"])
    runtime.data.weight_rerank = bool(retriever_update["enable_weight_rerank"])
    runtime.data.vec_w = float(retriever_update["vector_weight"])
    runtime.data.kw_w = float(retriever_update["keyword_weight"])
    runtime.data.mmr_lambda_val = float(retriever_update["mmr_lambda"])
    runtime.data.rerank_on = bool(retriever_update["enable_reranker"])
    runtime.data.rerank_provider = str(retriever_update["reranker_provider"])
    runtime.data.rerank_top_n = int(retriever_update["reranker_top_n"])
    runtime.data.sparse_retrieval_enabled = normalization.sparse_enabled
    runtime.data.sparse_retrieval_provider = normalization.sparse_provider
    runtime.data.hierarchy_recall_enabled = normalization.hierarchy.enabled
    runtime.data.hierarchy_family_collapse = normalization.hierarchy.family_collapse
    runtime.data.hierarchy_family_aggregation = normalization.hierarchy.family_aggregation
    runtime.data.hierarchy_tree_dedup = normalization.hierarchy.tree_dedup
    runtime.data.hierarchy_parent_depth = normalization.hierarchy.parent_depth
    runtime.data.hierarchy_sibling_window = normalization.hierarchy.sibling_window
    runtime.data.hierarchy_overfetch_factor = normalization.hierarchy.overfetch_factor


SETUP_OPERATIONS = (
    StreamOperation(agentic_phase, streams=True),
    StreamOperation(select_model_and_prompt, streams=True),
    StreamOperation(rewrite_and_apply_industry_rules, streams=True),
    StreamOperation(classify_modality_and_contract, streams=False),
    StreamOperation(route_query, streams=False),
)

__all__ = ["SETUP_OPERATIONS"]
