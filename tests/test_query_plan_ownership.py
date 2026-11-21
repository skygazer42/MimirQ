from dataclasses import replace
from uuid import uuid4

import pytest

from tests.query_model_fixtures import ModelReplies


def _request(**overrides):
    from app.rag.retrieval.planning.contracts import (
        IndustryQuerySettings,
        QueryExpansionBudget,
        QueryPreparationRequest,
        RetrievalRequest,
        RewriteSettings,
    )

    preferences = {
        "tenant_id": uuid4(),
        "account_id": "actor",
        "document_ids": [uuid4()],
        "top_k": 5,
        "retrieval_mode": "hybrid",
        "intent_router": False,
        "adaptive_router": False,
        "channel_budget_policy": {},
        "enable_multi_query": False,
        "enable_hyde": False,
        "enable_query_decomposition": False,
        "enable_kg_query_expansion": False,
        **overrides,
    }
    preparation = QueryPreparationRequest(
        "Explain SSO",
        "(No conversation history)",
        RewriteSettings(False, "kb_followup.v1", 0.0, 400),
        IndustryQuerySettings(False, (), 16, 2000),
        False,
    )
    return RetrievalRequest(preparation, preferences, QueryExpansionBudget(0, 0, 0, 0.0))


@pytest.fixture(autouse=True)
def _isolated_generation(monkeypatch):
    from app.infrastructure.config import settings
    from app.query import expand

    monkeypatch.setattr(settings, "ENABLE_STEP_BACK_QUERY", False)
    monkeypatch.setattr(expand, "load_base_dictionary_rules", lambda: {})


def test_query_plan_contains_normalized_options_owned_stages_and_budgeted_variants():
    from app.rag.retrieval.planning import planner as query_planning
    from app.rag.retrieval.planning.contracts import QueryExpansionBudget

    request = _request(query_aliases={"SSO": ["single sign-on", "identity entry"]}, enable_query_alias_expansion=True)
    request = replace(request, budget=QueryExpansionBudget(1, 0, 0, 0.0))
    models = ModelReplies()
    plan = query_planning.prepare_query_plan(request, models=models)
    assert plan.queries == [
        ("main", "Explain SSO"),
        ("alias", "Explain single sign-on"),
    ]
    assert plan.query == "Explain SSO"
    assert plan.retriever_options["k"] == 5
    assert plan.retriever_options["tenant_id"] == request.options["tenant_id"]
    assert plan.deterministic.alias.queries == ["Explain single sign-on", "Explain identity entry"]
    assert plan.variant_stage.query_expansion_budget_meta["degraded"] is True
    assert models.calls == []


def test_query_plan_does_not_mutate_caller_preferences():
    from app.rag.retrieval.planning import planner as query_planning

    request = _request(retrieval_profile="recall50")
    original = dict(request.options)
    query_planning.prepare_query_plan(request, models=ModelReplies())
    assert request.options == original


def test_query_plan_applies_routed_mode_before_model_generation():
    from app.rag.retrieval.planning import planner as query_planning

    request = _request(retrieval_mode="auto", enable_hyde=True)
    request = replace(request, preparation=replace(request.preparation, question="Traceback ValueError in handler.py"))
    models = ModelReplies()
    plan = query_planning.prepare_query_plan(request, models=models)
    assert plan.routing.normalization.request_retrieval_mode == "keyword"
    assert plan.models.hyde.used is False and ("resolve", "hyde") not in models.calls


def test_plan_keeps_model_failure_without_discarding_the_main_query():
    from app.rag.retrieval.planning import planner as query_planning

    failure = TimeoutError("query variants unavailable")
    plan = query_planning.prepare_query_plan(
        _request(enable_multi_query=True), models=ModelReplies(multi_query=failure)
    )
    assert plan.models.multi_query.failure is failure
    assert plan.queries[0][0] == "main" and plan.queries[0][1] == "Explain SSO"


def test_applied_channel_budget_policy_reaches_actual_retriever_options():
    from app.rag.retrieval.planning import planner as query_planning

    budgets = {"vector": 1, "lexical": 2}
    request = _request(channel_budget_policy={"profiles": {"default": {"fusion_budgets": budgets}}})
    plan = query_planning.prepare_query_plan(request, models=ModelReplies())
    assert plan.routing.channel_metadata["used"] is True
    assert plan.retriever_options["fusion_budgets"] == budgets
    assert plan.retriever_options["fusion_strategy"] == "budgeted_rrf"


@pytest.mark.parametrize(
    "field", ["query_expansion_max_queries", "query_expansion_token_budget", "query_expansion_latency_budget_ms"]
)
def test_invalid_budget_is_rejected_before_models_and_does_not_become_unbounded(field):
    from app.rag.retrieval.stages import preparation

    with pytest.raises((TypeError, ValueError)):
        preparation._build_retrieval_request(
            {field: "invalid budget"}, question="base", history_text="(No conversation history)"
        )


def test_request_adapter_excludes_sessions_engines_and_unrelated_runtime_fields():
    from app.rag.retrieval.stages import preparation

    state = {"db": object(), "engine": object(), "metrics": {"old": 1}, "top_k": 7, "document_ids": [uuid4()]}
    request = preparation._build_retrieval_request(state, question="base", history_text="(No conversation history)")
    assert request.options == {"top_k": 7, "document_ids": state["document_ids"]}
