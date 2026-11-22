import asyncio
from dataclasses import replace

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel


def _request():
    from app.rag.retrieval.planning.contracts import IndustryQuerySettings, QueryPreparationRequest, RewriteSettings

    return QueryPreparationRequest(
        "What is it?",
        "We discussed Ragvia.",
        RewriteSettings(True, "kb_followup.v1", 0.0, 400),
        IndustryQuerySettings(False, (), 16, 2000),
        False,
    )


@pytest.mark.asyncio
async def test_async_preparation_returns_the_same_owned_stages_and_attempt_fact():
    from app.rag.retrieval.planning import planner as query_planning

    class Model:
        model_name = "fixture"

        async def ainvoke(self, *, question, history):
            await asyncio.sleep(0)
            return '"What is Ragvia?"'

    class Models:
        def rewrite(self, **kwargs):
            return Model()

    result = await query_planning.prepare_query_async(_request(), models=Models())
    assert result.query == "What is Ragvia?"
    assert result.rewrite.used and result.rewrite.attempted
    assert result.rewrite.failure is None


@pytest.mark.asyncio
async def test_disabled_async_rewrite_has_no_attempt_and_does_not_resolve_models():
    from app.rag.retrieval.planning import planner as query_planning

    class Models:
        def rewrite(self, **kwargs):
            pytest.fail("disabled preparation resolved a model")

    request = _request()
    result = await query_planning.prepare_query_async(
        replace(request, rewrite=replace(request.rewrite, enabled=False)), models=Models()
    )
    assert result.query == request.question and result.rewrite.attempted is False


@pytest.mark.asyncio
async def test_standard_rewrite_feeds_industry_before_publishing_effective_query(monkeypatch):
    from app.infrastructure.config import settings
    from app.rag.retrieval.planning import planner as query_planning
    from app.rag.runtime.streaming import setup as standard_stream_setup
    from app.rag.runtime.streaming.state import StandardStreamState

    monkeypatch.setattr(settings, "QUERY_REWRITE_STRATEGY", "kb_followup.v1")
    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", True)
    observed = []

    def industry(query, **kwargs):
        observed.append(query)
        return query + " industry", {"enabled": True, "used": True}

    class NoModule:
        def __getattr__(self, name):
            raise AssertionError("preparation looked up engine module: " + name)

    monkeypatch.setattr(query_planning, "apply_industry_rules_query_expansion", industry)
    engine = NoModule()
    engine.models = {}
    runtime = StandardStreamState(
        engine=engine,
        payload={
            "question": "What is it?",
            "history_text": "We discussed Ragvia.",
            "rewrite_enabled": True,
            "llm": FakeListChatModel(responses=["What is Ragvia?"]),
            "industry_rules_enabled": True,
            "industry_rules_rulesets": [],
        },
    )
    stream = standard_stream_setup.rewrite_and_apply_industry_rules(runtime)
    try:
        event = await anext(stream)
        assert event["type"] == "rewrite" and event["data"]["rewritten"] == "What is Ragvia? industry"
        assert observed == ["What is Ragvia?"]
        with pytest.raises(StopAsyncIteration):
            await anext(stream)
        assert runtime.data.query_for_retrieval == "What is Ragvia? industry"
    finally:
        await stream.aclose()
