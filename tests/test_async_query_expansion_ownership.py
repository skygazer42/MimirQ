import asyncio
import threading
from dataclasses import replace
from uuid import uuid4

import pytest

from tests.query_model_fixtures import AsyncReplies, ModelReplies, model_query_request, model_query_settings


@pytest.mark.asyncio
async def test_async_model_strategies_share_results_and_run_natively_in_the_callers_loop() -> None:
    from app.rag.retrieval.planning import model_expansion as model_query_expansion

    models = AsyncReplies()
    asynchronous = await model_query_expansion.expand_model_queries_async(model_query_request(), models=models)
    synchronous = model_query_expansion.expand_model_queries(model_query_request(), models=ModelReplies())
    assert asynchronous.multi_query.queries == synchronous.multi_query.queries
    assert asynchronous.hyde.text == synchronous.hyde.text
    assert asynchronous.step_back.parse_metadata == synchronous.step_back.parse_metadata
    assert asynchronous.decomposition.queries == synchronous.decomposition.queries
    invocations = [call for call in models.calls if call[0] == "invoke"]
    assert [call[1] for call in invocations] == ["multi_query", "hyde", "step_back", "decomposition"]
    assert {call[3] for call in invocations} == {threading.get_ident()}


@pytest.mark.asyncio
async def test_async_disabled_strategies_and_keyword_hyde_do_not_resolve_unused_models() -> None:
    from app.rag.retrieval.planning import model_expansion as model_query_expansion

    settings = model_query_settings()
    settings = replace(
        settings,
        multi_query=replace(settings.multi_query, count=0),
        step_back=replace(settings.step_back, enabled=False),
        decomposition=replace(settings.decomposition, enabled=False),
    )
    models = AsyncReplies()
    result = await model_query_expansion.expand_model_queries_async(
        model_query_request(mode="keyword", settings=settings), models=models
    )
    assert models.calls == []
    assert not (result.multi_query.used or result.hyde.used or result.step_back.used or result.decomposition.used)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["multi_query", "hyde", "step_back", "decomposition"])
async def test_async_model_failure_retains_the_original_exception(kind) -> None:
    from app.rag.retrieval.planning import model_expansion as model_query_expansion

    failure = TimeoutError(kind + " timed out")
    result = await model_query_expansion.expand_model_queries_async(
        model_query_request(), models=AsyncReplies(**{kind: failure})
    )
    outcome = getattr(result, kind)
    assert outcome.failure is failure and outcome.used is False


@pytest.mark.asyncio
@pytest.mark.parametrize("text", [None, 0, {"unexpected": "object"}])
async def test_async_text_contract_failure_is_visible_and_does_not_discard_other_strategies(text) -> None:
    from app.rag.retrieval.planning import model_expansion as model_query_expansion

    result = await model_query_expansion.expand_model_queries_async(
        model_query_request(), models=AsyncReplies(hyde=text)
    )
    assert isinstance(result.hyde.failure, ValueError) and result.hyde.used is False
    assert result.multi_query.queries == ["first", "second"]
    assert result.step_back.used and result.decomposition.used


@pytest.mark.asyncio
async def test_async_decomposition_retains_defined_heuristic_policy_and_original_failure() -> None:
    from app.rag.retrieval.planning import model_expansion as model_query_expansion

    failure = TimeoutError("decompose unavailable")
    settings = replace(model_query_settings().decomposition, heuristic_enabled=True)
    result = await model_query_expansion.decompose_query_async(
        "合同的有效期限是多少？付款的具体条件是什么？", settings=settings, models=AsyncReplies(decomposition=failure)
    )
    assert result.queries == ["合同的有效期限是多少", "付款的具体条件是什么"]
    assert result.failure is failure and result.parse_metadata["method"] == "heuristic"


@pytest.mark.asyncio
async def test_async_model_request_cancellation_closes_the_await_and_leaves_the_loop_responsive() -> None:
    from app.rag.retrieval.planning import model_expansion as model_query_expansion

    entered, closed = asyncio.Event(), asyncio.Event()
    blocker = asyncio.Event()

    class Models(AsyncReplies):
        def multi_query(self, **kwargs):
            class Model:
                model_name = "blocking"

                async def ainvoke(self, *, query):
                    entered.set()
                    try:
                        await blocker.wait()
                    finally:
                        closed.set()

            return Model()

    task = asyncio.create_task(model_query_expansion.expand_model_queries_async(model_query_request(), models=Models()))
    try:
        await asyncio.wait_for(entered.wait(), timeout=1)
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert closed.is_set() and task.done()
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_async_required_model_resolution_error_propagates_before_optional_degradation() -> None:
    from app.rag.retrieval.planning import model_expansion as model_query_expansion

    failure = ValueError("missing required model")

    class Models(AsyncReplies):
        def multi_query(self, **kwargs):
            raise failure

    with pytest.raises(ValueError) as caught:
        await model_query_expansion.expand_model_queries_async(model_query_request(), models=Models())
    assert caught.value is failure


def _kg_request_and_settings():
    from app.rag.retrieval.planning.contracts import KGExpansionSettings, KGQueryRequest, KGQueryScope

    return KGQueryRequest("Ragvia", KGQueryScope(uuid4(), "actor", (), uuid4())), KGExpansionSettings(
        True, True, 3, 2, 0.15, ()
    )


@pytest.mark.asyncio
async def test_async_kg_expansion_uses_the_same_projection_on_the_callers_loop(monkeypatch) -> None:
    from app.rag.kg import pipeline
    from app.rag.retrieval.planning import knowledge_graph as kg_query_expansion

    request, settings = _kg_request_and_settings()
    caller_loop = asyncio.get_running_loop()
    payload = {
        "entities": [
            {"name": "API", "type": "Technology", "weight": 0.9},
            {"name": "Storage", "type": "Technology", "weight": 0.5},
        ]
    }

    async def search(**kwargs):
        assert asyncio.get_running_loop() is caller_loop
        assert kwargs["tenant_id"] == request.scope.tenant_id
        assert kwargs["account_id"] == "actor"
        await asyncio.sleep(0)
        return payload

    monkeypatch.setattr(pipeline, "kg_search", search)
    result = await kg_query_expansion.expand_kg_query_async(request, settings=settings)
    assert result.failure is None and result.response is payload
    assert result.queries == ["Ragvia API", "Ragvia Storage"]
    assert result.entities_total == result.entities_selected == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [[], {"entities": "wrong shape"}])
async def test_async_kg_contract_errors_remain_visible(monkeypatch, payload) -> None:
    from app.rag.kg import pipeline
    from app.rag.retrieval.planning import knowledge_graph as kg_query_expansion

    request, settings = _kg_request_and_settings()

    async def search(**kwargs):
        return payload

    monkeypatch.setattr(pipeline, "kg_search", search)
    result = await kg_query_expansion.expand_kg_query_async(request, settings=settings)
    assert isinstance(result.failure, TypeError) and result.queries == []


@pytest.mark.asyncio
async def test_async_kg_admission_skips_the_service_and_cancellation_propagates(monkeypatch) -> None:
    from app.rag.kg import pipeline
    from app.rag.retrieval.planning import knowledge_graph as kg_query_expansion

    request, settings = _kg_request_and_settings()
    calls = []
    failure = asyncio.CancelledError("KG cancelled")

    async def search(**kwargs):
        calls.append(kwargs)
        raise failure

    monkeypatch.setattr(pipeline, "kg_search", search)
    skipped = await kg_query_expansion.expand_kg_query_async(
        replace(request, scope=replace(request.scope, tenant_id=None)), settings=settings
    )
    assert skipped.response is None and calls == []
    with pytest.raises(asyncio.CancelledError) as caught:
        await kg_query_expansion.expand_kg_query_async(request, settings=settings)
    assert caught.value is failure
