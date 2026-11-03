"""Query expansion phases for standard RAG streaming."""

import time
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


async def expand_aliases_dictionary_and_init_kg(runtime: StandardStreamState) -> None:
    # Step 0.5: Query Expansion (Multi-Query / HyDE, optional).
    runtime.data.alias_elapsed = 0.0
    runtime.data.alias_used = False
    runtime.data.alias_meta: dict[str, Any] = {"enabled": False, "used": False}
    runtime.data.alias_queries: list[str] = []

    runtime.data.alias_enabled = runtime.data.enable_query_alias_expansion
    if runtime.data.alias_enabled is None:
        # Default behavior: if a dataset provided aliases, apply them unless explicitly disabled.
        runtime.data.alias_enabled = bool(runtime.data.query_aliases)
    if bool(runtime.data.alias_enabled):
        runtime.data.t0 = time.time()
        runtime.data.alias_queries, runtime.data.alias_meta = runtime.module.generate_alias_queries(
            query=runtime.data.query_for_retrieval,
            aliases=runtime.data.query_aliases,
            max_queries=(
                5 if runtime.data.query_alias_max_queries is None else int(runtime.data.query_alias_max_queries or 0)
            ),
        )
        runtime.data.alias_elapsed = time.time() - runtime.data.t0
        runtime.data.alias_used = bool(runtime.data.alias_queries)

    # Deterministic dictionary expansion (bounded, auditable).
    runtime.data.dict_elapsed = 0.0
    runtime.data.dict_used = False
    runtime.data.dict_meta: dict[str, Any] = {"enabled": False, "used": False}
    runtime.data.dict_expansions: list[dict[str, Any]] = []
    try:
        from app.query.expand import generate_dictionary_expansions, load_base_dictionary_rules

        runtime.data.t0 = time.time()
        runtime.data.dict_expansions, runtime.data.dict_meta = generate_dictionary_expansions(
            query=runtime.data.query_for_retrieval,
            rules=load_base_dictionary_rules(),
            max_expansions_total=5,
            max_expansions_per_rule=1,
        )
        runtime.data.dict_elapsed = time.time() - runtime.data.t0
        runtime.data.dict_used = bool(runtime.data.dict_expansions)
    except Exception as exc:  # noqa: BLE001
        runtime.data.dict_elapsed = 0.0
        runtime.data.dict_used = False
        runtime.data.dict_expansions = []
        runtime.data.dict_meta = {"enabled": False, "used": False, "error": str(exc)[:200]}

    # KG query expansion (entity names, optional).
    #
    # Purpose: provide extra retrieval queries derived from KG entity recall
    # to reduce false negatives, with clear attribution ("kgq").
    runtime.data.kg_result_cached: dict[str, Any] | None = None
    runtime.data.kg_query_expansion_enabled = (
        bool(getattr(settings, "RAG_KG_QUERY_EXPANSION_ENABLED", False))
        if runtime.data.enable_kg_query_expansion is None
        else bool(runtime.data.enable_kg_query_expansion)
    )
    runtime.data.kg_query_expansion_used = False
    runtime.data.kg_query_expansion_elapsed = 0.0
    runtime.data.kg_query_expansion_error: str | None = None
    runtime.data.kg_query_expansion_entities_total = 0
    runtime.data.kg_query_expansion_entities_selected = 0
    runtime.data.kg_query_expansion_queries: list[str] = []
    runtime.data.kg_query_expansion_entity_names: list[str] = []


def _kg_query_expansion_allowed(runtime: StandardStreamState) -> bool:
    has_scope = bool(
        runtime.data.kg_document_ids or runtime.data.kg_dataset_id is not None or runtime.data.kg_dataset_ids
    )
    has_account_scope = bool(
        runtime.data.account_id is not None or (runtime.data.kg_dataset_id is None and not runtime.data.kg_dataset_ids)
    )
    return bool(
        runtime.data.kg_query_expansion_enabled
        and getattr(settings, "KG_ENABLED", False)
        and getattr(settings, "KG_CHAT_ENABLED", False)
        and runtime.data.tenant_id is not None
        and has_scope
        and has_account_scope
    )


def _score_kg_entities(runtime: StandardStreamState) -> None:
    runtime.data.scored = []
    for runtime.data.ent in runtime.data.entities:
        if not isinstance(runtime.data.ent, dict) or runtime.data.exclude_all:
            continue
        runtime.data.etype = str(runtime.data.ent.get("type") or "").strip()
        if runtime.data.etype and runtime.data.etype.casefold() in runtime.data.exclude_fold:
            continue
        runtime.data.name = (runtime.data.ent.get("name") or "").strip()
        if not runtime.data.name:
            continue
        try:
            runtime.data.w = float(runtime.data.ent.get("weight", 0.0) or 0.0)
        except Exception:
            runtime.data.w = 0.0
        if runtime.data.w >= runtime.data.min_weight:
            runtime.data.scored.append((runtime.data.w, runtime.data.name))


def _select_kg_entity_names(runtime: StandardStreamState) -> None:
    runtime.data.scored.sort(key=lambda item: (-item[0], item[1]))
    runtime.data.seen_names = set()
    runtime.data.base_folded = runtime.data.query_for_retrieval.casefold()
    runtime.data.selected_names = []
    for _weight, name in runtime.data.scored:
        key = name.casefold() if name.isascii() else name
        if key in runtime.data.seen_names:
            continue
        runtime.data.seen_names.add(key)
        if key and key in runtime.data.base_folded:
            continue
        runtime.data.selected_names.append(name)
        if runtime.data.max_entities > 0 and len(runtime.data.selected_names) >= runtime.data.max_entities:
            break


def _build_kg_expansion_queries(runtime: StandardStreamState) -> None:
    for name in runtime.data.kg_query_expansion_entity_names:
        query = f"{runtime.data.query_for_retrieval} {name}".strip()
        if len(query) > 500:
            query = query[:500] + "..."
        runtime.data.kg_query_expansion_queries.append(query)
        if runtime.data.max_queries > 0 and len(runtime.data.kg_query_expansion_queries) >= runtime.data.max_queries:
            break


async def configure_corrective_retrieval(runtime: StandardStreamState) -> None:

    runtime.data.decompose_used = bool(runtime.data.sub_questions)

    runtime.data.corrective_enabled = bool(getattr(settings, "RAG_CORRECTIVE_ENABLED", False))
    runtime.data.corrective_max_attempts = max(1, min(int(getattr(settings, "RAG_CORRECTIVE_MAX_ATTEMPTS", 2) or 2), 3))
    runtime.data.corrective_min_faithfulness = float(
        getattr(settings, "RAG_CORRECTIVE_MIN_FAITHFULNESS_SCORE", 0.75) or 0.75
    )
    runtime.data.corrective_second_profile = (
        str(getattr(settings, "RAG_CORRECTIVE_SECOND_PASS_PROFILE", "recall50") or "recall50").strip().lower()
        or "recall50"
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
    runtime.data.corrective_second_enable_mq = bool(
        getattr(settings, "RAG_CORRECTIVE_SECOND_PASS_ENABLE_MULTI_QUERY", True)
    )
    runtime.data.corrective_second_mq_count = max(
        0,
        min(
            int(getattr(settings, "RAG_CORRECTIVE_SECOND_PASS_MULTI_QUERY_COUNT", 5) or 5),
            int(getattr(settings, "MULTI_QUERY_COUNT_CAP", 8) or 8),
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
    runtime.data.retrieval_queries_base = [item for item in plan.queries if item[0] != "mq"]
    runtime.data.retrieval_queries = list(plan.queries)
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
