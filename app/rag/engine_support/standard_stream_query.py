"""Query expansion phases for standard RAG streaming."""

from typing import Any

from app.core.config import settings
from app.rag.engine_support.query_model_calls import EngineQueryModels
from app.rag.engine_support.standard_stream_state import (
    StandardStreamState,
    StreamOperation,
)
from app.rag.retrieval.orchestration.query_contracts import QueryExpansionRequest
from app.rag.retrieval.orchestration.query_options import parse_query_expansion_budget
from app.rag.retrieval.orchestration.query_planning import complete_query_plan_async


async def configure_corrective_retrieval(runtime: StandardStreamState) -> None:

    runtime.data.decompose_used = bool(runtime.data.sub_questions)

    runtime.data.corrective_enabled = bool(settings.RAG_CORRECTIVE_ENABLED)
    runtime.data.corrective_max_attempts = max(1, min(int(settings.RAG_CORRECTIVE_MAX_ATTEMPTS), 3))
    runtime.data.corrective_min_faithfulness = float(settings.RAG_CORRECTIVE_MIN_FAITHFULNESS_SCORE)
    runtime.data.corrective_second_profile = (
        str(settings.RAG_CORRECTIVE_SECOND_PASS_PROFILE).strip().lower() or "recall50"
    )
    if runtime.data.corrective_second_profile not in {
        "recall20",
        "recall50",
        "coverage80",
        "expanded",
        "hierarchy_recall20",
        "hierarchy_recall20_expand",
    }:
        runtime.data.corrective_second_profile = "recall50"
    runtime.data.corrective_second_enable_mq = bool(settings.RAG_CORRECTIVE_SECOND_PASS_ENABLE_MULTI_QUERY)
    runtime.data.corrective_second_mq_count = max(
        0,
        min(
            int(settings.RAG_CORRECTIVE_SECOND_PASS_MULTI_QUERY_COUNT),
            int(settings.MULTI_QUERY_COUNT_CAP),
        ),
    )
    runtime.data.corrective_reason_codes: list[str] = []
    runtime.data.corrective_attempts: list[dict[str, Any]] = []
    runtime.data.corrective_used = False
    runtime.data.corrective_attempt_count = 1


async def prepare_query_plan(runtime: StandardStreamState) -> None:
    prepared = runtime.data.prepared_query_outcome
    routing = runtime.data.query_routing_outcome
    request = QueryExpansionRequest(
        prepared=prepared,
        routing=routing,
        budget=parse_query_expansion_budget(routing.effective_options),
        model_retrieval_mode=routing.normalization.request_retrieval_mode,
        multi_query_last=True,
    )
    plan = await complete_query_plan_async(
        request,
        models=EngineQueryModels(lambda: runtime.engine, selected_model=runtime.data.llm),
    )
    runtime.data.query_plan = plan

    alias = plan.deterministic.alias
    runtime.data.alias_elapsed = alias.elapsed_sec
    runtime.data.alias_used = bool(alias.queries)
    runtime.data.alias_meta = alias.metadata
    runtime.data.alias_queries = list(alias.queries)
    runtime.data.alias_enabled = plan.alias_settings.enabled

    dictionary = plan.deterministic.dictionary
    runtime.data.dict_elapsed = dictionary.elapsed_sec
    runtime.data.dict_used = bool(dictionary.expansions)
    runtime.data.dict_meta = dictionary.metadata
    runtime.data.dict_expansions = list(dictionary.expansions)

    kg = plan.kg
    runtime.data.kg_result_cached = kg.response
    runtime.data.kg_query_expansion_enabled = kg.enabled
    runtime.data.kg_query_expansion_used = kg.used
    runtime.data.kg_query_expansion_elapsed = kg.elapsed_sec
    runtime.data.kg_query_expansion_error = str(kg.failure)[:200] if kg.failure is not None else None
    runtime.data.kg_query_expansion_entities_total = kg.entities_total
    runtime.data.kg_query_expansion_entities_selected = kg.entities_selected
    runtime.data.kg_query_expansion_queries = list(kg.queries)
    runtime.data.kg_query_expansion_entity_names = list(kg.entity_names)

    multi = plan.models.multi_query
    runtime.data.multi_query = multi
    runtime.data.multi_query_elapsed = multi.elapsed_sec
    runtime.data.multi_query_used = multi.used
    runtime.data.multi_query_model_used = multi.model_used
    runtime.data.multi_query_parse_meta = multi.parse_metadata
    runtime.data.multi_queries = list(multi.queries)
    runtime.data.mq_enabled = plan.model_settings.multi_query.enabled
    runtime.data.mq_n = plan.model_settings.multi_query.count
    runtime.data.mq_temp = plan.model_settings.multi_query.temperature
    runtime.data.mq_max_chars = plan.model_settings.multi_query.max_chars
    experiment = plan.model_settings.multi_query.experiment
    runtime.data.multi_query_ab_test_key = experiment.key
    runtime.data.multi_query_ab_variant = experiment.variant
    runtime.data.multi_query_ab_seed = experiment.seed
    runtime.data.multi_query_ab_forced = experiment.forced

    hyde = plan.models.hyde
    runtime.data.hyde_enabled = hyde.enabled
    runtime.data.hyde_used = hyde.used
    runtime.data.hyde_elapsed = hyde.elapsed_sec
    runtime.data.hyde_model_used = hyde.model_used
    runtime.data.hyde_text = hyde.text

    step_back = plan.models.step_back
    runtime.data.step_back_enabled = step_back.enabled
    runtime.data.step_back_temp = plan.model_settings.step_back.temperature
    runtime.data.step_back_max_chars = plan.model_settings.step_back.max_chars
    runtime.data.step_back_output_max = plan.model_settings.step_back.output_max_chars
    runtime.data.step_back_used = step_back.used
    runtime.data.step_back_elapsed = step_back.elapsed_sec
    runtime.data.step_back_model_used = step_back.model_used
    runtime.data.step_back_parse_meta = step_back.parse_metadata
    runtime.data.step_back_query = step_back.text

    decomposition = plan.models.decomposition
    runtime.data.decompose_enabled = plan.model_settings.decomposition.enabled
    runtime.data.decompose_used = decomposition.used
    runtime.data.decompose_elapsed = decomposition.elapsed_sec
    runtime.data.decompose_model_used = decomposition.model_used
    runtime.data.decompose_parse_meta = decomposition.parse_metadata
    runtime.data.sub_questions = list(decomposition.queries)
    runtime.data.clause_fastlane_queries = list(plan.clause_queries)
    runtime.data.lightweight_subqueries = list(plan.lightweight_queries)

    variant_stage = plan.variant_stage
    runtime.data.query_expansion_budget_meta = variant_stage.query_expansion_budget_meta
    runtime.data.query_expansion_budget_max_queries = variant_stage.query_expansion_budget_max_queries
    runtime.data.query_expansion_budget_max_candidates = variant_stage.query_expansion_budget_max_candidates
    runtime.data.query_expansion_budget_token_budget = variant_stage.query_expansion_budget_token_budget
    runtime.data.query_expansion_budget_latency_ms = variant_stage.query_expansion_budget_latency_ms


QUERY_OPERATIONS = (
    StreamOperation(prepare_query_plan, streams=False),
    StreamOperation(configure_corrective_retrieval, streams=False),
)

__all__ = ["QUERY_OPERATIONS"]
