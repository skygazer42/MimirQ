"""Query preparation operations with explicit inputs, model calls and stage outcomes."""

import time
from dataclasses import dataclass

from app.infrastructure.config import settings as configured_settings
from app.query.expand import generate_alias_queries
from app.query.routing import should_rewrite_query
from app.rag.industry_rules.runtime import apply_industry_rules_query_expansion
from app.rag.llm.prompts.query_rewrite import build_query_rewrite_strategy_spec
from app.rag.policy.query_expansion import build_clause_fastlane_queries, build_lightweight_subquery_queries
from app.rag.retrieval.planning import knowledge_graph as kg_query_expansion
from app.rag.retrieval.planning import model_expansion as model_query_expansion
from app.rag.retrieval.planning.contracts import (
    AliasQueryOutcome,
    AliasQuerySettings,
    AsyncQueryModels,
    AsyncQueryVariantModels,
    AsyncRewriteModels,
    DeterministicExpansionRequest,
    DeterministicQueryExpansions,
    DictionaryQueryOutcome,
    IndustryQueryOutcome,
    KGExpansionSettings,
    KGQueryExpansion,
    KGQueryRequest,
    KGQueryScope,
    ModelQueryExpansions,
    ModelQueryRequest,
    ModelQuerySettings,
    PreparedQuery,
    QueryExpansionRequest,
    QueryModels,
    QueryPlan,
    QueryPreparationRequest,
    QueryVariantModels,
    RetrievalRequest,
    RewriteConfiguration,
    RewriteModels,
    RewriteOutcome,
    TemporalQueryOutcome,
)
from app.rag.retrieval.planning.options import (
    parse_model_query_overrides,
    resolve_alias_query_settings,
    resolve_kg_expansion_settings,
    resolve_model_query_settings,
)
from app.rag.retrieval.planning.routing import resolve_query_routing
from app.rag.retrieval.planning.variants import QueryVariantStageInput, build_query_variant_stage
from app.rag.retrieval.ranking.knowledge_graph import _resolve_kg_scope
from app.rag.retrieval.ranking.temporal import detect_temporal_intent
from app.rag.retrieval.results import _log_orchestrator_fallback


@dataclass(frozen=True)
class _QueryPlanStageInputs:
    deterministic: DeterministicQueryExpansions
    aliases: AliasQuerySettings
    kg_request: KGQueryRequest
    kg_settings: KGExpansionSettings


def _rewrite_configuration(request: QueryPreparationRequest) -> RewriteConfiguration | None:
    if not request.rewrite.enabled:
        return None
    spec = build_query_rewrite_strategy_spec(request.rewrite.strategy)
    return RewriteConfiguration(
        spec["strategy_id"], spec["strategy_hash"], request.rewrite.temperature, request.rewrite.max_chars
    )


def _rewrite_allowed(request: QueryPreparationRequest, configuration: RewriteConfiguration) -> bool:
    return bool(
        request.history_text != "(No conversation history)"
        and len(request.question) <= configuration.max_chars
        and should_rewrite_query(request.question)
    )


def _rewrite_result(
    request: QueryPreparationRequest,
    configuration: RewriteConfiguration,
    raw: str,
    elapsed: float,
    model_used: str | None,
) -> RewriteOutcome:
    text = raw.strip().strip('"')
    query = text if text else request.question
    return RewriteOutcome(query, query != request.question, elapsed, model_used, configuration, attempted=True)


def rewrite_query(request: QueryPreparationRequest, *, models: RewriteModels) -> RewriteOutcome:
    configuration = _rewrite_configuration(request)
    if configuration is None or not _rewrite_allowed(request, configuration):
        return RewriteOutcome(request.question, False, 0.0, None, configuration)
    model = models.rewrite(strategy_id=configuration.strategy_id, temperature=configuration.temperature)
    started = time.perf_counter()
    try:
        raw = model.invoke(question=request.question, history=request.history_text)
        return _rewrite_result(request, configuration, raw, time.perf_counter() - started, model.model_name)
    except Exception as exc:
        _log_orchestrator_fallback("prepare_query.rewrite", exc)
        return RewriteOutcome(
            request.question, False, time.perf_counter() - started, model.model_name, configuration, exc, attempted=True
        )


async def rewrite_query_async(request: QueryPreparationRequest, *, models: AsyncRewriteModels) -> RewriteOutcome:
    configuration = _rewrite_configuration(request)
    if configuration is None or not _rewrite_allowed(request, configuration):
        return RewriteOutcome(request.question, False, 0.0, None, configuration)
    model = models.rewrite(strategy_id=configuration.strategy_id, temperature=configuration.temperature)
    started = time.perf_counter()
    try:
        raw = await model.ainvoke(question=request.question, history=request.history_text)
        return _rewrite_result(request, configuration, raw, time.perf_counter() - started, model.model_name)
    except Exception as exc:
        _log_orchestrator_fallback("prepare_query.rewrite", exc)
        return RewriteOutcome(
            request.question, False, time.perf_counter() - started, model.model_name, configuration, exc, attempted=True
        )


def prepare_query(request: QueryPreparationRequest, *, models: RewriteModels) -> PreparedQuery:
    return complete_query_preparation(request, rewrite=rewrite_query(request, models=models))


async def prepare_query_async(request: QueryPreparationRequest, *, models: AsyncRewriteModels) -> PreparedQuery:
    rewrite = await rewrite_query_async(request, models=models)
    return complete_query_preparation(request, rewrite=rewrite)


def complete_query_preparation(request: QueryPreparationRequest, *, rewrite: RewriteOutcome) -> PreparedQuery:
    industry_settings = request.industry
    try:
        query, metadata = apply_industry_rules_query_expansion(
            rewrite.query,
            enabled=industry_settings.enabled,
            ruleset_names=industry_settings.rulesets,
            max_aliases=industry_settings.max_aliases,
            max_query_chars=industry_settings.max_query_chars,
        )
        industry = IndustryQueryOutcome(query, metadata)
    except Exception as exc:
        _log_orchestrator_fallback("prepare_query.industry", exc)
        industry = IndustryQueryOutcome(
            rewrite.query,
            {
                "enabled": industry_settings.enabled,
                "used": False,
                "error": f"industry_rules_exception:{str(exc)[:160]}",
            },
            exc,
        )
    temporal = TemporalQueryOutcome(request.temporal_enabled, {"detected": False, "reason_codes": []})
    if request.temporal_enabled:
        try:
            temporal = TemporalQueryOutcome(True, detect_temporal_intent(industry.query))
        except Exception as exc:
            _log_orchestrator_fallback("prepare_query.temporal", exc)
            temporal = TemporalQueryOutcome(True, {"detected": False, "reason_codes": [], "error": str(exc)[:200]}, exc)
    return PreparedQuery(rewrite, industry, temporal)


def expand_deterministic_queries(request: DeterministicExpansionRequest) -> DeterministicQueryExpansions:
    alias = AliasQueryOutcome([], {"enabled": False, "used": False}, 0.0)
    if request.alias.enabled:
        started = time.perf_counter()
        queries, metadata = generate_alias_queries(
            query=request.query, aliases=request.alias.aliases, max_queries=request.alias.max_queries
        )
        alias = AliasQueryOutcome(queries, metadata, time.perf_counter() - started)
    started = time.perf_counter()
    try:
        from app.query.expand import generate_dictionary_expansions, load_base_dictionary_rules

        expansions, metadata = generate_dictionary_expansions(
            query=request.query,
            rules=load_base_dictionary_rules(),
            max_expansions_total=5,
            max_expansions_per_rule=1,
        )
        dictionary = DictionaryQueryOutcome(expansions, metadata, time.perf_counter() - started)
    except Exception as exc:
        _log_orchestrator_fallback("expand_deterministic_queries.dictionary", exc)
        dictionary = DictionaryQueryOutcome(
            [], {"enabled": False, "used": False, "error": str(exc)[:200]}, time.perf_counter() - started, exc
        )
    return DeterministicQueryExpansions(alias, dictionary)


def prepare_query_plan(request: RetrievalRequest, *, models: QueryModels) -> QueryPlan:
    prepared = prepare_query(request.preparation, models=models)
    routing = resolve_query_routing(prepared.query, options=request.options)
    return complete_query_plan(
        QueryExpansionRequest(prepared, routing, request.budget, routing.normalization.request_retrieval_mode),
        models=models,
    )


async def prepare_query_plan_async(request: RetrievalRequest, *, models: AsyncQueryModels) -> QueryPlan:
    prepared = await prepare_query_async(request.preparation, models=models)
    routing = resolve_query_routing(prepared.query, options=request.options)
    return await complete_query_plan_async(
        QueryExpansionRequest(prepared, routing, request.budget, routing.normalization.request_retrieval_mode),
        models=models,
    )


def _deterministic_and_kg_request(
    request: QueryExpansionRequest,
) -> tuple[DeterministicQueryExpansions, AliasQuerySettings, KGQueryRequest]:
    options = request.routing.effective_options
    aliases = resolve_alias_query_settings(
        enabled=options.get("enable_query_alias_expansion"),
        aliases=options.get("query_aliases"),
        max_queries=options.get("query_alias_max_queries"),
    )
    deterministic = expand_deterministic_queries(DeterministicExpansionRequest(request.prepared.query, aliases))
    documents, dataset, datasets = _resolve_kg_scope(options)
    kg_request = KGQueryRequest(
        request.prepared.query,
        KGQueryScope(
            options.get("tenant_id"),
            options.get("account_id"),
            None if documents is None else tuple(documents),
            dataset,
            tuple(datasets),
        ),
    )
    return deterministic, aliases, kg_request


def _resolve_query_plan_stage_inputs(request: QueryExpansionRequest) -> _QueryPlanStageInputs:
    options = request.routing.effective_options
    deterministic, aliases, kg_request = _deterministic_and_kg_request(request)
    return _QueryPlanStageInputs(
        deterministic,
        aliases,
        kg_request,
        resolve_kg_expansion_settings(enabled=options.get("enable_kg_query_expansion")),
    )


def _build_model_query_request(request: QueryExpansionRequest) -> ModelQueryRequest:
    model_settings = resolve_model_query_settings(parse_model_query_overrides(request.routing.effective_options))
    return ModelQueryRequest(request.prepared.query, request.model_retrieval_mode, model_settings)


def complete_query_plan(request: QueryExpansionRequest, *, models: QueryVariantModels) -> QueryPlan:
    inputs = _resolve_query_plan_stage_inputs(request)
    kg = kg_query_expansion.expand_kg_query(inputs.kg_request, settings=inputs.kg_settings)
    model_request = _build_model_query_request(request)
    generated = model_query_expansion.expand_model_queries(model_request, models=models)
    return _complete_query_plan(request, inputs.deterministic, inputs.aliases, kg, generated, model_request.settings)


async def complete_query_plan_async(request: QueryExpansionRequest, *, models: AsyncQueryVariantModels) -> QueryPlan:
    inputs = _resolve_query_plan_stage_inputs(request)
    kg = await kg_query_expansion.expand_kg_query_async(inputs.kg_request, settings=inputs.kg_settings)
    model_request = _build_model_query_request(request)
    generated = await model_query_expansion.expand_model_queries_async(model_request, models=models)
    return _complete_query_plan(request, inputs.deterministic, inputs.aliases, kg, generated, model_request.settings)


def _complete_query_plan(
    request: QueryExpansionRequest,
    deterministic: DeterministicQueryExpansions,
    aliases: AliasQuerySettings,
    kg: KGQueryExpansion,
    generated: ModelQueryExpansions,
    model_config: ModelQuerySettings,
) -> QueryPlan:
    prepared, routing = request.prepared, request.routing
    clauses = build_clause_fastlane_queries(prepared.query)
    lightweight = (
        build_lightweight_subquery_queries(
            prepared.query,
            max_queries=configured_settings.RETRIEVAL_LIGHTWEIGHT_SUBQUERY_MAX_QUERIES,
            min_query_chars=configured_settings.RETRIEVAL_LIGHTWEIGHT_SUBQUERY_MIN_QUERY_CHARS,
        )
        if configured_settings.RETRIEVAL_LIGHTWEIGHT_SUBQUERY_ENABLED
        else []
    )
    elapsed_ms = 1000.0 * (
        deterministic.alias.elapsed_sec
        + deterministic.dictionary.elapsed_sec
        + kg.elapsed_sec
        + generated.multi_query.elapsed_sec
        + generated.hyde.elapsed_sec
        + generated.step_back.elapsed_sec
        + generated.decomposition.elapsed_sec
    )
    stage = build_query_variant_stage(
        QueryVariantStageInput(
            query_for_retrieval=prepared.query,
            alias_queries=deterministic.alias.queries,
            dict_expansions=deterministic.dictionary.expansions,
            kg_query_expansion_queries=kg.queries,
            clause_fastlane_queries=clauses,
            lightweight_subqueries=lightweight,
            multi_queries=generated.multi_query.queries,
            step_back_used=generated.step_back.used,
            step_back_query=generated.step_back.text,
            sub_questions=generated.decomposition.queries,
            hyde_used=generated.hyde.used,
            hyde_text=generated.hyde.text,
            budget=request.budget,
            query_expansion_elapsed_ms=elapsed_ms,
            multi_query_last=request.multi_query_last,
        )
    )
    return QueryPlan(
        prepared, routing, deterministic, kg, generated, stage, clauses, lightweight, model_config, aliases
    )
