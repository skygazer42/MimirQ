"""Resolve actual query options once against the validated runtime settings."""

from collections.abc import Mapping
from typing import Any

from app.core.config import settings
from app.core.utils import parse_csv
from app.rag.retrieval.orchestration.query_contract import QueryContractDefaults
from app.rag.retrieval.orchestration.query_contracts import (
    AliasQuerySettings,
    DecompositionSettings,
    IndustryQuerySettings,
    KGExpansionSettings,
    ModelQueryOverrides,
    ModelQuerySettings,
    MultiQueryExperiment,
    MultiQuerySettings,
    QueryExpansionBudget,
    QueryPreparationOverrides,
    QueryPreparationRequest,
    RewriteSettings,
    SparseQuerySettings,
    TextQuerySettings,
)

QUERY_PLANNING_OPTION_KEYS = frozenset(
    (
        "account_id",
        "adaptive_router",
        "adaptive_router_policy",
        "alpha",
        "channel_budget_policy",
        "channel_budget_policy_path",
        "contextual_followup_enabled",
        "contextual_followup_latency_budget_ms",
        "contextual_followup_max_docs",
        "contextual_followup_max_hops",
        "contextual_followup_max_query_chars",
        "contextual_followup_max_terms",
        "contextual_followup_min_term_chars",
        "contextual_followup_mode",
        "contextual_followup_top_k",
        "dataset_id",
        "dataset_ids",
        "document_ids",
        "enable_hierarchy_recall",
        "enable_hyde",
        "enable_kg_query_expansion",
        "enable_multi_query",
        "enable_query_alias_expansion",
        "enable_query_decomposition",
        "enable_query_rewrite",
        "enable_reranker",
        "enable_weight_rerank",
        "fusion_budgets",
        "fusion_min_scores",
        "fusion_strategy",
        "fusion_weights",
        "hierarchy_family_aggregation",
        "hierarchy_family_collapse",
        "hierarchy_overfetch_factor",
        "hierarchy_parent_depth",
        "hierarchy_sibling_window",
        "hierarchy_tree_dedup",
        "industry_rules_enabled",
        "industry_rules_rulesets",
        "intent_router",
        "intent_router_model",
        "intent_router_model_confidence_min",
        "intent_router_model_path",
        "intent_router_policy",
        "keyword_weight",
        "lexical_db_hybrid_fallback_only",
        "lexical_db_hybrid_metadata_exact_fallback_enabled",
        "metadata_exact_db_fallback_enabled",
        "metadata_filter",
        "mmr_lambda",
        "multi_query_ab_seed",
        "multi_query_ab_test_key",
        "multi_query_ab_variant",
        "multi_query_count",
        "multi_query_max_chars",
        "multi_query_temperature",
        "must_recall",
        "must_recall_auto_expected_source_keys_enabled",
        "must_recall_auto_required_anchor_fields_enabled",
        "must_recall_expected_source_keys",
        "must_recall_required_anchor_fields",
        "query_alias_max_queries",
        "query_aliases",
        "query_expansion_latency_budget_ms",
        "query_rewrite_max_chars",
        "query_rewrite_strategy",
        "query_rewrite_temperature",
        "reranker_provider",
        "reranker_top_n",
        "retrieval_contract_mode",
        "retrieval_mode",
        "retrieval_overfetch_max_k",
        "retrieval_overfetch_multiplier",
        "retrieval_profile",
        "score_threshold",
        "sparse_retrieval_enabled",
        "sparse_retrieval_provider",
        "table_ids",
        "tenant_id",
        "top_k",
        "vector_weight",
        "visible_evidence_only",
    )
)


def query_contract_defaults() -> QueryContractDefaults:
    return QueryContractDefaults(
        retrieval_top_k=settings.RETRIEVAL_TOP_K,
        similarity_threshold=float(settings.SIMILARITY_THRESHOLD),
        enable_reranker=settings.ENABLE_RERANKER,
        reranker_provider=settings.RERANKER_PROVIDER,
        reranker_top_n=settings.RERANKER_TOP_N,
        retrieval_contract_mode=settings.RETRIEVAL_CONTRACT_MODE,
        hard_fallback_enabled_setting=settings.RETRIEVAL_HARD_FALLBACK_ENABLED,
        hard_fallback_mode_setting=settings.RETRIEVAL_HARD_FALLBACK_MODE,
        hard_fallback_top_k_setting=settings.RETRIEVAL_HARD_FALLBACK_TOP_K,
        visible_evidence_only_setting=settings.RAG_VISIBLE_EVIDENCE_ONLY_ENABLED,
        evidence_span_strict_setting=settings.RAG_EVIDENCE_REQUIRE_SPANS_ENABLED,
        retrieval_fusion_strategy=settings.RETRIEVAL_FUSION_STRATEGY,
        retrieval_mmr_lambda=float(settings.RETRIEVAL_MMR_LAMBDA),
    )


def resolve_query_preparation_request(
    question: str, history_text: str, overrides: QueryPreparationOverrides, *, temporal_enabled: bool
) -> QueryPreparationRequest:
    from app.core.model_execution import reject_retired_provider

    reject_retired_provider(
        settings.SPARSE_RETRIEVAL_PROVIDER if overrides.sparse_provider is None else overrides.sparse_provider,
        capability="sparse",
    )
    return QueryPreparationRequest(
        question,
        history_text,
        RewriteSettings(
            settings.ENABLE_QUERY_REWRITE if overrides.enable_rewrite is None else overrides.enable_rewrite,
            overrides.rewrite_strategy or settings.QUERY_REWRITE_STRATEGY,
            settings.QUERY_REWRITE_TEMPERATURE
            if overrides.rewrite_temperature is None
            else overrides.rewrite_temperature,
            settings.QUERY_REWRITE_MAX_CHARS if overrides.rewrite_max_chars is None else overrides.rewrite_max_chars,
        ),
        SparseQuerySettings(
            settings.SPARSE_RETRIEVAL_ENABLED if overrides.sparse_enabled is None else overrides.sparse_enabled,
            settings.SPARSE_RETRIEVAL_PROVIDER if overrides.sparse_provider is None else overrides.sparse_provider,
        ),
        IndustryQuerySettings(
            settings.RAG_INDUSTRY_RULES_ENABLED if overrides.industry_enabled is None else overrides.industry_enabled,
            settings.RAG_INDUSTRY_RULES_RULESETS
            if overrides.industry_rulesets is None
            else overrides.industry_rulesets,
            settings.RAG_INDUSTRY_RULES_MAX_ALIASES,
            settings.RAG_INDUSTRY_RULES_MAX_QUERY_CHARS,
        ),
        temporal_enabled,
    )


def resolve_alias_query_settings(
    *, enabled: bool | None, aliases: dict[str, list[str]] | None, max_queries: int | None
) -> AliasQuerySettings:
    return AliasQuerySettings(
        bool(aliases) if enabled is None else enabled, aliases, 5 if max_queries is None else max_queries
    )


def resolve_kg_expansion_settings(*, enabled: bool | None) -> KGExpansionSettings:
    return KGExpansionSettings(
        settings.RAG_KG_QUERY_EXPANSION_ENABLED if enabled is None else enabled,
        settings.KG_ENABLED and settings.KG_CHAT_ENABLED,
        max(0, settings.RAG_KG_QUERY_EXPANSION_MAX_ENTITIES),
        max(0, settings.RAG_KG_QUERY_EXPANSION_MAX_QUERIES),
        settings.RAG_KG_QUERY_EXPANSION_MIN_ENTITY_WEIGHT,
        tuple(parse_csv(settings.RAG_KG_QUERY_EXPANSION_EXCLUDE_ENTITY_TYPES)),
    )


def resolve_model_query_settings(overrides: ModelQueryOverrides) -> ModelQuerySettings:
    variant = overrides.multi_query_ab_variant.strip().lower() if overrides.multi_query_ab_variant is not None else None
    forced = overrides.enable_multi_query is None and variant in {"on", "enabled", "treatment", "mq"}
    key = overrides.multi_query_ab_test_key.strip() if overrides.multi_query_ab_test_key is not None else None
    experiment = MultiQueryExperiment(key, variant, overrides.multi_query_ab_seed, forced)
    count = settings.MULTI_QUERY_COUNT if overrides.multi_query_count is None else overrides.multi_query_count
    temperature = (
        settings.MULTI_QUERY_TEMPERATURE
        if overrides.multi_query_temperature is None
        else overrides.multi_query_temperature
    )
    max_chars = (
        settings.MULTI_QUERY_MAX_CHARS if overrides.multi_query_max_chars is None else overrides.multi_query_max_chars
    )
    multi = MultiQuerySettings(
        settings.ENABLE_MULTI_QUERY or forced if overrides.enable_multi_query is None else overrides.enable_multi_query,
        max(0, min(count, max(0, settings.MULTI_QUERY_COUNT_CAP))),
        min(2.0, max(0.0, temperature)),
        max(0, max_chars),
        experiment,
    )
    hyde = TextQuerySettings(
        settings.ENABLE_HYDE if overrides.enable_hyde is None else overrides.enable_hyde,
        settings.HYDE_TEMPERATURE,
        max(0, settings.HYDE_MAX_CHARS),
        max(0, settings.HYDE_OUTPUT_MAX_CHARS),
    )
    step_back = TextQuerySettings(
        settings.ENABLE_STEP_BACK_QUERY,
        min(2.0, max(0.0, settings.STEP_BACK_TEMPERATURE)),
        max(0, settings.STEP_BACK_MAX_CHARS),
        max(0, settings.STEP_BACK_OUTPUT_MAX_CHARS),
    )
    decomposition = DecompositionSettings(
        settings.ENABLE_QUERY_DECOMPOSITION
        if overrides.enable_query_decomposition is None
        else overrides.enable_query_decomposition,
        max(0, min(settings.QUERY_DECOMPOSITION_MAX_SUBQUESTIONS, 8)),
        max(0, settings.QUERY_DECOMPOSITION_MIN_CHARS),
        max(0, settings.QUERY_DECOMPOSITION_MAX_CHARS),
        settings.QUERY_DECOMPOSITION_TEMPERATURE,
        settings.QUERY_DECOMPOSITION_HEURISTIC_FALLBACK_ENABLED,
        bool(settings.LLM_API_KEY.strip()),
    )
    return ModelQuerySettings(multi, hyde, step_back, decomposition)


def _normalize_multi_query_label(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip()


def parse_model_query_overrides(options: Mapping[str, Any]) -> ModelQueryOverrides:
    return ModelQueryOverrides(
        enable_multi_query=None if options.get("enable_multi_query") is None else bool(options["enable_multi_query"]),
        multi_query_count=None if options.get("multi_query_count") is None else int(options["multi_query_count"]),
        multi_query_temperature=None
        if options.get("multi_query_temperature") is None
        else float(options["multi_query_temperature"]),
        multi_query_max_chars=None
        if options.get("multi_query_max_chars") is None
        else int(options["multi_query_max_chars"]),
        enable_hyde=None if options.get("enable_hyde") is None else bool(options["enable_hyde"]),
        enable_query_decomposition=None
        if options.get("enable_query_decomposition") is None
        else bool(options["enable_query_decomposition"]),
        multi_query_ab_test_key=(_normalize_multi_query_label(options.get("multi_query_ab_test_key"))),
        multi_query_ab_variant=(_normalize_multi_query_label(options.get("multi_query_ab_variant"))),
        multi_query_ab_seed=options.get("multi_query_ab_seed"),
    )


def parse_query_expansion_budget(options: Mapping[str, Any]) -> QueryExpansionBudget:
    def count(key: str) -> int:
        value = options.get(key)
        return 0 if value is None else max(0, int(value))

    latency = options.get("query_expansion_latency_budget_ms")
    return QueryExpansionBudget(
        count("query_expansion_max_queries"),
        count("query_expansion_max_candidates"),
        count("query_expansion_token_budget"),
        0.0 if latency is None else max(0.0, float(latency)),
    )
