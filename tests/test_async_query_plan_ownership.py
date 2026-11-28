import asyncio
from dataclasses import replace

import pytest

from tests.query_model_fixtures import AsyncReplies, ModelReplies
from tests.test_query_plan_ownership import _request


@pytest.fixture(autouse=True)
def _isolate_queries(monkeypatch):
    from app.infrastructure.config import settings
    from app.query import expand

    monkeypatch.setattr(expand, "load_base_dictionary_rules", lambda: {})
    monkeypatch.setattr(settings, "ENABLE_STEP_BACK_QUERY", True)
    monkeypatch.setattr(settings, "QUERY_DECOMPOSITION_MIN_CHARS", 0)
    monkeypatch.setattr(settings, "QUERY_DECOMPOSITION_HEURISTIC_FALLBACK_ENABLED", False)
    monkeypatch.setattr(settings, "LLM_API_KEY", "test-key")


def _model_request():
    return _request(enable_multi_query=True, enable_hyde=True, enable_query_decomposition=True)


@pytest.mark.asyncio
async def test_async_plan_composes_the_same_queries_and_retriever_options_as_sync():
    from app.rag.retrieval.planning import planner as query_planning

    request = _model_request()
    synchronous = query_planning.prepare_query_plan(request, models=ModelReplies())
    asynchronous = await query_planning.prepare_query_plan_async(request, models=AsyncReplies())
    assert asynchronous.queries == synchronous.queries
    assert [kind for kind, query in asynchronous.queries] == ["main", "mq", "mq", "step_back", "subq", "subq", "hyde"]
    assert asynchronous.retriever_options == synchronous.retriever_options


@pytest.mark.asyncio
async def test_stream_completion_uses_prepared_routing_and_preserves_its_query_priority():
    from app.rag.retrieval.planning import planner as query_planning
    from app.rag.retrieval.planning.contracts import QueryExpansionBudget, QueryExpansionRequest
    from app.rag.retrieval.planning.routing import resolve_query_routing

    request = _model_request()
    prepared = query_planning.prepare_query(request.preparation, models=ModelReplies())
    routing = resolve_query_routing(prepared.query, options=request.options)
    plan = await query_planning.complete_query_plan_async(
        QueryExpansionRequest(prepared, routing, QueryExpansionBudget(2, 0, 0, 0.0), "hybrid", multi_query_last=True),
        models=AsyncReplies(),
    )
    assert plan.prepared is prepared and plan.routing is routing
    assert list(plan.queries) == [
        ("main", "Explain SSO"),
        ("step_back", "broader view"),
        ("subq", "part one"),
    ]
    assert plan.variant_stage.query_expansion_budget_meta["degraded"] is True


@pytest.mark.asyncio
async def test_async_plan_applies_native_rewrite_before_model_strategies():
    from app.rag.retrieval.planning import planner as query_planning

    class Replies(AsyncReplies):
        def rewrite(self, **kwargs):
            class Rewrite:
                model_name = "rewrite"

                async def ainvoke(self, *, question, history):
                    await asyncio.sleep(0)
                    return "What is Ragvia?"

            return Rewrite()

    request = _model_request()
    request = replace(
        request,
        preparation=replace(
            request.preparation,
            question="What is it?",
            history_text="We discussed Ragvia.",
            rewrite=replace(request.preparation.rewrite, enabled=True),
        ),
    )
    replies = Replies()
    plan = await query_planning.prepare_query_plan_async(request, models=replies)
    assert plan.query == "What is Ragvia?" and plan.prepared.rewrite.attempted
    assert {call[2] for call in replies.calls if call[0] == "invoke"} == {"What is Ragvia?"}


@pytest.mark.asyncio
async def test_async_plan_retains_optional_failure_and_propagates_cancellation():
    from app.rag.retrieval.planning import planner as query_planning

    failure = TimeoutError("variant provider unavailable")
    plan = await query_planning.prepare_query_plan_async(_model_request(), models=AsyncReplies(multi_query=failure))
    assert plan.models.multi_query.failure is failure and plan.queries[0][0] == "main"
    with pytest.raises(asyncio.CancelledError):
        await query_planning.prepare_query_plan_async(
            _model_request(), models=AsyncReplies(multi_query=asyncio.CancelledError())
        )
