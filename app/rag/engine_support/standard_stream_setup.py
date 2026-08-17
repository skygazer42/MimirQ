"""Setup and routing phases for standard RAG streaming."""

import time
from collections.abc import AsyncGenerator
from typing import Any
from uuid import UUID

from app.core.config import settings
from app.rag.engine_support.standard_stream_state import (
    StandardStreamState,
    StreamOperation,
)


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
    if runtime.data.rewrite_enabled:
        runtime.data.spec = runtime.module.build_query_rewrite_strategy_spec(
            getattr(settings, "QUERY_REWRITE_STRATEGY", None)
        )
        runtime.data.rewrite_strategy_id = str(runtime.data.spec.get("strategy_id") or "").strip() or None
        runtime.data.rewrite_strategy_hash = str(runtime.data.spec.get("strategy_hash") or "").strip() or None
        try:
            runtime.data.rewrite_temperature = float(settings.QUERY_REWRITE_TEMPERATURE or 0.0)
        except Exception:
            runtime.data.rewrite_temperature = 0.0
        try:
            runtime.data.rewrite_max_chars = int(settings.QUERY_REWRITE_MAX_CHARS or 0)
        except Exception:
            runtime.data.rewrite_max_chars = 0

    # Step 0: Query Rewrite (optional).
    if (
        runtime.data.rewrite_enabled
        and runtime.data.history_text != "(No conversation history)"
        and len(runtime.data.question) <= int(runtime.data.rewrite_max_chars or 0)
        and runtime.module.should_rewrite_query(runtime.data.question)
    ):
        runtime.data.rewrite_llm = runtime.engine.models.get("fast") or runtime.data.llm
        runtime.data.rewrite_model_used = getattr(runtime.data.rewrite_llm, "model_name", None) or getattr(
            runtime.data.rewrite_llm, "model", None
        )
        try:
            runtime.data.prompt_template = runtime.module.get_query_rewrite_prompt_template(
                runtime.data.rewrite_strategy_id
            )
            runtime.data.rewrite_prompt = runtime.module.ChatPromptTemplate.from_template(runtime.data.prompt_template)
            runtime.data.rewrite_chain = (
                runtime.data.rewrite_prompt
                | runtime.data.rewrite_llm.bind(temperature=runtime.data.rewrite_temperature)
                | runtime.module.StrOutputParser()
            )
            runtime.data.rw_start = time.time()
            runtime.data.rewritten = await runtime.data.rewrite_chain.ainvoke(
                {"history": runtime.data.history_text, "question": runtime.data.question}
            )
            runtime.data.rewrite_elapsed = time.time() - runtime.data.rw_start
            runtime.data.rewritten = (runtime.data.rewritten or "").strip().strip('"')
            if runtime.data.rewritten:
                runtime.data.query_for_retrieval = runtime.data.rewritten
        except Exception:
            runtime.data.query_for_retrieval = runtime.data.question
            runtime.data.rewrite_elapsed = 0.0

        runtime.data.rewrite_used = runtime.data.query_for_retrieval != runtime.data.question
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

    runtime.data.industry_rules_enabled_effective = (
        bool(runtime.data.industry_rules_enabled)
        if runtime.data.industry_rules_enabled is not None
        else bool(getattr(settings, "RAG_INDUSTRY_RULES_ENABLED", False))
    )
    runtime.data.industry_rules_meta: dict[str, Any] = {
        "enabled": bool(runtime.data.industry_rules_enabled_effective),
        "used": False,
    }
    try:
        from app.rag.industry_rules.runtime import apply_industry_rules_query_expansion

        runtime.data.query_for_retrieval, runtime.data.industry_rules_meta = apply_industry_rules_query_expansion(
            runtime.data.query_for_retrieval,
            enabled=runtime.data.industry_rules_enabled_effective,
            ruleset_names=(
                runtime.data.industry_rules_rulesets
                if runtime.data.industry_rules_rulesets is not None
                else getattr(settings, "RAG_INDUSTRY_RULES_RULESETS", "")
            ),
            max_aliases=int(getattr(settings, "RAG_INDUSTRY_RULES_MAX_ALIASES", 16) or 16),
            max_query_chars=int(getattr(settings, "RAG_INDUSTRY_RULES_MAX_QUERY_CHARS", 2000) or 2000),
        )
    except Exception as exc:  # noqa: BLE001
        runtime.data.industry_rules_meta = {
            "enabled": bool(runtime.data.industry_rules_enabled_effective),
            "used": False,
            "error": f"industry_rules_exception:{str(exc)[:160]}",
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

    # Capture caller intent (kept for trace/metrics).
    runtime.data.mode_req = runtime.data.retrieval_mode or "hybrid"
    runtime.data.profile_req = runtime.data.retrieval_profile
    runtime.data.contract_req = (
        runtime.data.retrieval_contract_mode
        if runtime.data.retrieval_contract_mode is not None
        else getattr(settings, "RETRIEVAL_CONTRACT_MODE", "")
    )
    if bool(runtime.data.must_recall) and not str(runtime.data.contract_req or "").strip():
        runtime.data.contract_req = "must_recall_strict"
    runtime.data.retrieval_contract_policy = runtime.module.resolve_retrieval_contract_policy(
        mode=runtime.data.contract_req,
        requested_top_k=int(runtime.data.top_k or 0),
        hard_fallback_enabled_setting=bool(getattr(settings, "RETRIEVAL_HARD_FALLBACK_ENABLED", False)),
        hard_fallback_mode_setting=str(getattr(settings, "RETRIEVAL_HARD_FALLBACK_MODE", "keyword") or "keyword"),
        hard_fallback_top_k_setting=int(getattr(settings, "RETRIEVAL_HARD_FALLBACK_TOP_K", 30) or 30),
        visible_evidence_only_setting=bool(getattr(settings, "RAG_VISIBLE_EVIDENCE_ONLY_ENABLED", False)),
        evidence_span_strict_setting=bool(getattr(settings, "RAG_EVIDENCE_REQUIRE_SPANS_ENABLED", False)),
    )
    runtime.data.retrieval_contract_mode_effective = str(
        runtime.data.retrieval_contract_policy.get("mode") or ""
    ).strip()

    # Step 0.25: Deterministic intent router (optional).
    #
    # Goal: map query "shape" (log/api/howto/faq) to retrieval presets and safe toggles.
    # Must be deterministic + PII-safe (no raw query in meta payloads).
    runtime.data.intent_router_enabled = (
        bool(runtime.data.intent_router)
        if runtime.data.intent_router is not None
        else bool(getattr(settings, "RAG_INTENT_ROUTER_ENABLED", False))
    )
    runtime.data.intent_router_meta: dict[str, Any] = {
        "enabled": bool(runtime.data.intent_router_enabled),
        "used": False,
    }


def _apply_intent_core_overrides(runtime: StandardStreamState) -> None:
    overrides = runtime.data.overrides
    if overrides.get("retrieval_mode") is not None:
        runtime.data.retrieval_mode = str(overrides.get("retrieval_mode") or "").strip() or runtime.data.retrieval_mode
    if overrides.get("retrieval_profile") is not None:
        runtime.data.retrieval_profile = (
            str(overrides.get("retrieval_profile") or "").strip() or runtime.data.retrieval_profile
        )
    if overrides.get("top_k") is not None:
        runtime.data.top_k = int(overrides.get("top_k") or 0)
    if overrides.get("score_threshold") is not None:
        runtime.data.score_threshold = float(overrides.get("score_threshold") or 0.0)
    if overrides.get("enable_reranker") is not None:
        runtime.data.enable_reranker = bool(overrides.get("enable_reranker"))


def _apply_intent_feature_overrides(runtime: StandardStreamState) -> None:
    overrides = runtime.data.overrides
    if overrides.get("reranker_provider") is not None:
        runtime.data.reranker_provider = (
            str(overrides.get("reranker_provider") or "").strip() or runtime.data.reranker_provider
        )
    if overrides.get("reranker_top_n") is not None:
        runtime.data.reranker_top_n = int(overrides.get("reranker_top_n") or 0)
    if overrides.get("enable_weight_rerank") is not None:
        runtime.data.enable_weight_rerank = bool(overrides.get("enable_weight_rerank"))
    if overrides.get("enable_multi_query") is not None:
        runtime.data.enable_multi_query = bool(overrides.get("enable_multi_query"))
    if overrides.get("enable_query_alias_expansion") is not None:
        runtime.data.enable_query_alias_expansion = bool(overrides.get("enable_query_alias_expansion"))


async def apply_intent_router(runtime: StandardStreamState) -> None:
    if not runtime.data.intent_router_enabled:
        return
    try:
        runtime.data.overrides, runtime.data.intent_router_meta = runtime.module.route_retrieval_preset(
            query=runtime.data.query_for_retrieval,
            retrieval_mode=str(runtime.data.mode_req or ""),
            retrieval_profile=(str(runtime.data.profile_req).strip() if runtime.data.profile_req is not None else None),
            top_k=int(runtime.data.top_k or 0),
            score_threshold=float(runtime.data.score_threshold or 0.0),
            enable_reranker=bool(runtime.data.enable_reranker),
            enable_weight_rerank=bool(runtime.data.enable_weight_rerank),
            enable_multi_query=runtime.data.enable_multi_query,
            enable_query_alias_expansion=runtime.data.enable_query_alias_expansion,
            intent_router_policy=runtime.data.intent_router_policy,
        )
        if isinstance(runtime.data.overrides, dict):
            _apply_intent_core_overrides(runtime)
            _apply_intent_feature_overrides(runtime)
    except Exception as exc:  # noqa: BLE001
        runtime.data.intent_router_meta = {
            "enabled": True,
            "used": False,
            "error": f"intent_router_exception:{str(exc)[:160]}",
        }


async def normalize_retrieval_route(runtime: StandardStreamState) -> None:

    runtime.data.mode_used = runtime.module.normalize_retrieval_mode(runtime.data.retrieval_mode or "hybrid")
    runtime.data.mode_auto = False
    runtime.data.recall_bucket: str | None = None
    runtime.data.recall_bucket_routing = bool(getattr(settings, "RAG_RECALL_BUCKETS_ENABLED", False))
    runtime.data.mode_norm = (runtime.data.mode_used or "hybrid").lower().strip()
    if runtime.data.mode_norm == "auto":
        runtime.data.mode_auto = True
        if runtime.data.recall_bucket_routing:
            runtime.data.recall_bucket = runtime.module.guess_recall_bucket(runtime.data.query_for_retrieval)
            if runtime.data.recall_bucket in ("schema", "policy", "definition"):
                runtime.data.mode_used = "keyword"
            else:
                runtime.data.mode_used = runtime.module.guess_retrieval_mode(runtime.data.query_for_retrieval)
        else:
            runtime.data.mode_used = runtime.module.guess_retrieval_mode(runtime.data.query_for_retrieval)
        runtime.data.mode_norm = runtime.data.mode_used.lower().strip()
    if runtime.data.mode_norm not in ("hybrid", "vector", "keyword", "mmr"):
        runtime.data.mode_used = "hybrid"
        runtime.data.mode_norm = "hybrid"
    runtime.data.alpha_val = runtime.data.alpha if runtime.data.alpha is not None else 0.6
    runtime.data.weight_rerank = bool(runtime.data.enable_weight_rerank)
    runtime.data.vec_w = runtime.data.vector_weight if runtime.data.vector_weight is not None else 0.6
    runtime.data.kw_w = runtime.data.keyword_weight if runtime.data.keyword_weight is not None else 0.4
    runtime.data.mmr_lambda_val = (
        runtime.data.mmr_lambda if runtime.data.mmr_lambda is not None else settings.RETRIEVAL_MMR_LAMBDA
    )
    runtime.data.rerank_on = bool(runtime.data.enable_reranker)
    runtime.data.rerank_provider = runtime.data.reranker_provider or settings.RERANKER_PROVIDER or "llm"
    runtime.data.rerank_top_n = int(runtime.data.reranker_top_n or settings.RERANKER_TOP_N or 20)
    runtime.data.score_threshold_used = float(runtime.data.score_threshold or 0.0)


async def apply_recall_bucket_and_profile(runtime: StandardStreamState) -> None:

    if runtime.data.mode_auto and runtime.data.recall_bucket_routing and runtime.data.recall_bucket:
        if runtime.data.recall_bucket in ("schema", "policy", "definition"):
            runtime.data.score_threshold_used = 0.0
            runtime.data.vec_w = 0.2
            runtime.data.kw_w = 0.8
        elif runtime.data.recall_bucket == "procedure":
            runtime.data.vec_w = 0.7
            runtime.data.kw_w = 0.3
        elif runtime.data.recall_bucket == "numeric":
            runtime.data.vec_w = 0.5
            runtime.data.kw_w = 0.5

    runtime.data.profile_applied = runtime.module.apply_retrieval_profile_overrides(
        profile=runtime.data.retrieval_profile,
        top_k=int(runtime.data.top_k or 0),
        score_threshold=float(runtime.data.score_threshold_used or 0.0),
        retrieval_mode=runtime.data.mode_used,
        enable_reranker=runtime.data.rerank_on,
        reranker_provider=runtime.data.rerank_provider,
        reranker_top_n=runtime.data.rerank_top_n,
        enable_weight_rerank=runtime.data.enable_weight_rerank,
        retrieval_contract_mode=(
            runtime.data.retrieval_contract_mode
            if runtime.data.retrieval_contract_mode is not None
            else getattr(settings, "RETRIEVAL_CONTRACT_MODE", "")
        ),
        visible_evidence_only=(
            bool(runtime.data.visible_evidence_only) if runtime.data.visible_evidence_only is not None else None
        ),
    )
    runtime.data.profile_norm = str(runtime.data.profile_applied.get("retrieval_profile") or "").strip().lower()
    runtime.data.retrieval_profile = runtime.data.profile_applied.get("retrieval_profile")
    runtime.data.top_k = int(runtime.data.profile_applied.get("top_k") or 0)
    runtime.data.score_threshold_used = float(runtime.data.profile_applied.get("score_threshold") or 0.0)
    runtime.data.mode_used = str(runtime.data.profile_applied.get("retrieval_mode") or runtime.data.mode_used)
    if runtime.data.profile_applied.get("enable_reranker") is not None:
        runtime.data.rerank_on = bool(runtime.data.profile_applied.get("enable_reranker"))
    if runtime.data.profile_applied.get("reranker_provider"):
        runtime.data.rerank_provider = str(
            runtime.data.profile_applied.get("reranker_provider") or runtime.data.rerank_provider
        )
    if runtime.data.profile_applied.get("reranker_top_n") is not None:
        runtime.data.rerank_top_n = int(
            runtime.data.profile_applied.get("reranker_top_n") or runtime.data.rerank_top_n or 0
        )


async def apply_profile_feature_overrides(runtime: StandardStreamState) -> None:
    if runtime.data.profile_applied.get("enable_weight_rerank") is not None:
        runtime.data.enable_weight_rerank = bool(runtime.data.profile_applied.get("enable_weight_rerank"))
    if runtime.data.profile_applied.get("sparse_retrieval_enabled") is not None:
        runtime.data.sparse_retrieval_enabled = bool(runtime.data.profile_applied.get("sparse_retrieval_enabled"))
    if runtime.data.profile_applied.get("sparse_retrieval_provider"):
        runtime.data.sparse_retrieval_provider = str(runtime.data.profile_applied.get("sparse_retrieval_provider"))
    if runtime.data.profile_applied.get("enable_hierarchy_recall") is not None:
        runtime.data.enable_hierarchy_recall = bool(runtime.data.profile_applied.get("enable_hierarchy_recall"))
    if runtime.data.profile_applied.get("hierarchy_family_collapse") is not None:
        runtime.data.hierarchy_family_collapse = bool(runtime.data.profile_applied.get("hierarchy_family_collapse"))
    if runtime.data.profile_applied.get("hierarchy_overfetch_factor") is not None:
        runtime.data.hierarchy_overfetch_factor = int(
            runtime.data.profile_applied.get("hierarchy_overfetch_factor") or 1
        )
    if runtime.data.profile_applied.get("hierarchy_family_aggregation") is not None:
        runtime.data.hierarchy_family_aggregation = (
            str(runtime.data.profile_applied.get("hierarchy_family_aggregation") or "").strip().lower() or None
        )


async def refresh_contract_and_adaptive_route(runtime: StandardStreamState) -> None:
    if runtime.data.profile_applied.get("hierarchy_tree_dedup") is not None:
        runtime.data.hierarchy_tree_dedup = bool(runtime.data.profile_applied.get("hierarchy_tree_dedup"))
    if runtime.data.profile_applied.get("hierarchy_parent_depth") is not None:
        runtime.data.hierarchy_parent_depth = max(
            0, int(runtime.data.profile_applied.get("hierarchy_parent_depth") or 0)
        )
    if runtime.data.profile_applied.get("hierarchy_sibling_window") is not None:
        runtime.data.hierarchy_sibling_window = max(
            0, int(runtime.data.profile_applied.get("hierarchy_sibling_window") or 0)
        )
    if runtime.data.profile_applied.get("retrieval_contract_mode") is not None:
        runtime.data.retrieval_contract_mode = (
            str(runtime.data.profile_applied.get("retrieval_contract_mode") or "").strip() or None
        )
    if runtime.data.profile_applied.get("visible_evidence_only") is not None:
        runtime.data.visible_evidence_only = bool(runtime.data.profile_applied.get("visible_evidence_only"))

    runtime.data.contract_req = (
        runtime.data.retrieval_contract_mode
        if runtime.data.retrieval_contract_mode is not None
        else getattr(settings, "RETRIEVAL_CONTRACT_MODE", "")
    )
    if bool(runtime.data.must_recall) and not str(runtime.data.contract_req or "").strip():
        runtime.data.contract_req = "must_recall_strict"
    runtime.data.retrieval_contract_policy = runtime.module.resolve_retrieval_contract_policy(
        mode=runtime.data.contract_req,
        requested_top_k=int(runtime.data.top_k or 0),
        hard_fallback_enabled_setting=bool(getattr(settings, "RETRIEVAL_HARD_FALLBACK_ENABLED", False)),
        hard_fallback_mode_setting=str(getattr(settings, "RETRIEVAL_HARD_FALLBACK_MODE", "keyword") or "keyword"),
        hard_fallback_top_k_setting=int(getattr(settings, "RETRIEVAL_HARD_FALLBACK_TOP_K", 30) or 30),
        visible_evidence_only_setting=bool(getattr(settings, "RAG_VISIBLE_EVIDENCE_ONLY_ENABLED", False)),
        evidence_span_strict_setting=bool(getattr(settings, "RAG_EVIDENCE_REQUIRE_SPANS_ENABLED", False)),
    )
    runtime.data.retrieval_contract_mode_effective = str(
        runtime.data.retrieval_contract_policy.get("mode") or ""
    ).strip()
    runtime.data.adaptive_retrieval_overrides = runtime.engine._route_retrieval_params(runtime.data.complexity_score)
    runtime.data.adaptive_retrieval_used = bool(runtime.data.adaptive_retrieval_overrides)


async def apply_adaptive_route(runtime: StandardStreamState) -> None:
    if runtime.data.adaptive_retrieval_overrides:
        if runtime.data.adaptive_retrieval_overrides.get("top_k") is not None:
            runtime.data.top_k = max(
                1, int(runtime.data.adaptive_retrieval_overrides.get("top_k") or runtime.data.top_k or 1)
            )
        if runtime.data.adaptive_retrieval_overrides.get("enable_multi_query") is not None:
            runtime.data.enable_multi_query = bool(runtime.data.adaptive_retrieval_overrides.get("enable_multi_query"))
        if runtime.data.adaptive_retrieval_overrides.get("multi_query_count") is not None:
            runtime.data.multi_query_count = max(
                0, int(runtime.data.adaptive_retrieval_overrides.get("multi_query_count") or 0)
            )
        if runtime.data.adaptive_retrieval_overrides.get("retrieval_profile") is not None:
            runtime.data.retrieval_profile = (
                str(runtime.data.adaptive_retrieval_overrides.get("retrieval_profile") or "").strip()
                or runtime.data.retrieval_profile
            )
            runtime.data.profile_norm = str(runtime.data.retrieval_profile or "").strip().lower()
            if runtime.module.is_recall_first_profile(runtime.data.profile_norm):
                runtime.data.score_threshold_used = 0.0


SETUP_OPERATIONS = (
    StreamOperation(agentic_phase, streams=True),
    StreamOperation(select_model_and_prompt, streams=True),
    StreamOperation(rewrite_and_apply_industry_rules, streams=True),
    StreamOperation(classify_modality_and_contract, streams=False),
    StreamOperation(apply_intent_router, streams=False),
    StreamOperation(normalize_retrieval_route, streams=False),
    StreamOperation(apply_recall_bucket_and_profile, streams=False),
    StreamOperation(apply_profile_feature_overrides, streams=False),
    StreamOperation(refresh_contract_and_adaptive_route, streams=False),
    StreamOperation(apply_adaptive_route, streams=False),
)

__all__ = ["SETUP_OPERATIONS"]
