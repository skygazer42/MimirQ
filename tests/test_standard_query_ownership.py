from types import SimpleNamespace
from uuid import uuid4

import pytest
from langchain_core.language_models.fake_chat_models import FakeListChatModel
from langchain_core.prompts import ChatPromptTemplate


class NoModuleCollaborators(SimpleNamespace):
    def __getattr__(self, name):
        raise AssertionError("query phase used engine module collaborator: " + name)


def _runtime(**overrides):
    from app.api.schemas.conversations.chat import ChatRAGConfig
    from app.rag.retrieval.planning import planner as query_planning
    from app.rag.retrieval.planning.contracts import QueryPreparationOverrides
    from app.rag.retrieval.planning.options import QUERY_PLANNING_OPTION_KEYS, resolve_query_preparation_request
    from app.rag.retrieval.planning.routing import resolve_stream_query_routing
    from app.rag.runtime.model_routing import LlmRoutingMixin
    from app.rag.runtime.streaming.state import StandardStreamState

    class RuntimeEngine(LlmRoutingMixin, NoModuleCollaborators):
        pass

    selected = FakeListChatModel(responses=['["alternate"]', "hypothesis", "broader", '["part query"]'])
    engine = RuntimeEngine(
        models={},
        multi_query_prompt=ChatPromptTemplate.from_template("{query} {n}"),
        hyde_prompt=ChatPromptTemplate.from_template("{query}"),
        step_back_prompt=ChatPromptTemplate.from_template("{query}"),
        decompose_prompt=ChatPromptTemplate.from_template("{query} {n}"),
    )
    payload = {
        **ChatRAGConfig().model_dump(),
        "query_for_retrieval": "base query",
        "question": "base query",
        "mode_used": "hybrid",
        "llm": selected,
        "enable_query_alias_expansion": False,
        "query_aliases": None,
        "query_alias_max_queries": None,
        "enable_kg_query_expansion": False,
        "enable_multi_query": True,
        "multi_query_count": 2,
        "multi_query_temperature": 0.0,
        "multi_query_max_chars": 400,
        "enable_hyde": True,
        "enable_query_decomposition": True,
        "tenant_id": uuid4(),
        "account_id": "actor",
        "document_ids": [uuid4()],
        "dataset_id": None,
        "dataset_ids": [],
        "strict_visible": False,
        **overrides,
    }
    prepared = query_planning.prepare_query(
        resolve_query_preparation_request(
            payload["question"],
            "(No conversation history)",
            QueryPreparationOverrides(
                enable_rewrite=False,
                industry_enabled=False,
            ),
            temporal_enabled=False,
        ),
        models=SimpleNamespace(),
    )
    routing = resolve_stream_query_routing(
        prepared.query,
        options={key: value for key, value in payload.items() if key in QUERY_PLANNING_OPTION_KEYS},
        complexity_overrides={},
    )
    payload.update(prepared_query_outcome=prepared, query_routing_outcome=routing.routing)
    return StandardStreamState(engine=engine, payload=payload)


@pytest.mark.asyncio
async def test_standard_query_phases_consume_actual_shared_owners_and_selected_model(monkeypatch) -> None:
    from app.infrastructure.config import settings
    from app.query import expand
    from app.rag.runtime.streaming import query as standard_stream_query

    monkeypatch.setattr(settings, "ENABLE_STEP_BACK_QUERY", True)
    monkeypatch.setattr(settings, "QUERY_DECOMPOSITION_MIN_CHARS", 0)
    monkeypatch.setattr(settings, "QUERY_DECOMPOSITION_HEURISTIC_FALLBACK_ENABLED", False)
    monkeypatch.setattr(expand, "load_base_dictionary_rules", lambda: {})
    runtime = _runtime()
    await standard_stream_query.prepare_query_plan(runtime)
    assert runtime.data.multi_query.queries == ["alternate"]
    assert runtime.data.query_plan.models.hyde.text == "hypothesis"
    assert runtime.data.query_plan.models.step_back.text == "broader"
    assert runtime.data.query_plan.models.decomposition.queries == ["part query"]
    assert runtime.data.query_plan.models.decomposition.used is True
    assert [kind for kind, query in runtime.data.query_plan.queries] == ["main", "step_back", "subq", "hyde", "mq"]


@pytest.mark.asyncio
async def test_standard_query_plan_retains_its_model_result_when_metrics_are_projected(monkeypatch):
    from app.infrastructure.config import settings
    from app.query import expand
    from app.rag.runtime.streaming import query as standard_stream_query

    monkeypatch.setattr(settings, "ENABLE_STEP_BACK_QUERY", False)
    monkeypatch.setattr(expand, "load_base_dictionary_rules", lambda: {})
    runtime = _runtime(enable_hyde=False, enable_query_decomposition=False)
    await standard_stream_query.prepare_query_plan(runtime)
    assert runtime.data.multi_query is runtime.data.query_plan.models.multi_query
    assert runtime.data.multi_queries == ["alternate"]
    runtime.data.multi_queries.append("metrics-only projection")
    assert runtime.data.query_plan.models.multi_query.queries == ["alternate"]


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [[], {}])
async def test_standard_kg_consumers_do_not_repeat_rejected_or_empty_reads(monkeypatch, payload) -> None:
    from app.infrastructure.config import settings
    from app.query import expand
    from app.rag.kg import pipeline
    from app.rag.runtime.streaming import evidence as standard_stream_evidence
    from app.rag.runtime.streaming import query as standard_stream_query

    monkeypatch.setattr(settings, "KG_ENABLED", True)
    monkeypatch.setattr(settings, "KG_CHAT_ENABLED", True)
    monkeypatch.setattr(expand, "load_base_dictionary_rules", lambda: {})
    calls = []

    async def search(**kwargs):
        calls.append(kwargs)
        return payload

    monkeypatch.setattr(pipeline, "kg_search", search)
    runtime = _runtime(enable_kg_query_expansion=True)
    await standard_stream_query.prepare_query_plan(runtime)
    await standard_stream_evidence.recall_kg_context(runtime)
    assert len(calls) == 1
    assert runtime.data.kg_context == ""
    if isinstance(payload, list):
        assert runtime.data.kg_context_failure is runtime.data.query_plan.kg.failure
    else:
        assert runtime.data.kg_result_cached is payload and runtime.data.kg_context_failure is None


@pytest.mark.asyncio
async def test_standard_kg_context_checks_event_quotes_against_retrieved_chunks(monkeypatch) -> None:
    from langchain_core.documents import Document

    from app.infrastructure.config import settings
    from app.rag.kg.search.utils import format_events
    from app.rag.runtime.streaming import evidence as standard_stream_evidence

    monkeypatch.setattr(settings, "KG_ENABLED", True)
    monkeypatch.setattr(settings, "KG_CHAT_ENABLED", True)
    monkeypatch.setattr(settings, "RAG_CONTEXT_MAX_KG_TOKENS", 0)
    monkeypatch.setattr(settings, "RAG_CONTEXT_MAX_KG_CHARS", 10_000)
    document_id, chunk_id = uuid4(), uuid4()
    prefix = "旧版规则已作废。\n"
    quote = "审批通过后保留 30 天。"
    stale_quote = "审批通过后保留 60 天。"
    refs = {
        "evidence_quote": quote,
        "evidence_start_char": len(prefix),
        "evidence_end_char": len(prefix + quote),
    }
    events = [
        SimpleNamespace(
            id=uuid4(),
            title=title,
            summary="事件摘要",
            content="事件摘要",
            document_id=document_id,
            chunk_id=chunk_id,
            references=references,
        )
        for title, references in (
            ("当前规则", refs),
            ("过期引用", {**refs, "evidence_quote": stale_quote}),
            ("旧记录", None),
            ("错误偏移", {**refs, "evidence_start_char": -1}),
        )
    ]
    scores = {str(event.id): len(events) - index for index, event in enumerate(events)}
    ranked = format_events(events, scores, limit=len(events))
    runtime = _runtime(
        document_ids=[document_id],
        docs=[Document(id=str(chunk_id), page_content=prefix + quote)],
        query_plan=SimpleNamespace(kg=SimpleNamespace(failure=None, response={"events": ranked})),
    )

    await standard_stream_evidence.recall_kg_context(runtime)
    await standard_stream_evidence.join_context_sections(runtime)

    assert ranked[0]["evidence_quote"] == quote
    assert "evidence_quote" not in ranked[-1]
    assert "[Source excerpt] " + quote in runtime.data.context
    assert stale_quote not in runtime.data.context
    assert "[Event 3] 旧记录\n事件摘要" in runtime.data.context
    assert runtime.data.kg_context_failure is None


@pytest.mark.asyncio
async def test_stream_builds_the_actual_retriever_and_queries_from_the_plan(monkeypatch):
    from app.infrastructure.config import settings
    from app.query import expand
    from app.rag.retrieval.recall.retriever import HybridRetriever
    from app.rag.runtime.streaming import query as standard_stream_query
    from app.rag.runtime.streaming import retrieval as standard_stream_retrieval

    monkeypatch.setattr(settings, "ENABLE_STEP_BACK_QUERY", False)
    monkeypatch.setattr(expand, "load_base_dictionary_rules", lambda: {})
    runtime = _runtime(
        retrieval_profile=None,
        enable_hyde=False,
        enable_multi_query=False,
        enable_query_decomposition=False,
        top_k=7,
        retrieval_mode="keyword",
    )
    await standard_stream_query.prepare_query_plan(runtime)
    runtime.engine._build_stream_status_event = lambda **kwargs: None
    runtime.data.corrective_max_attempts = 2
    monkeypatch.setattr(standard_stream_retrieval, "hybrid_retriever", HybridRetriever())
    expected = list(runtime.data.query_plan.queries)
    runtime.data.alias_queries = ["obsolete alias projection"]
    runtime.data.multi_queries = ["obsolete model projection"]
    async for _event in standard_stream_retrieval.build_retriever_and_base_queries(runtime):
        pass
    await standard_stream_retrieval.extend_queries_and_prepare_plan(runtime)
    assert runtime.data.retriever.k == 7
    assert runtime.data.retriever.retrieval_mode == "keyword"
    assert runtime.data.retrieval_queries == expected


@pytest.mark.asyncio
async def test_corrective_query_generation_uses_the_selected_model_and_extends_retry_queries(monkeypatch) -> None:
    from app.infrastructure.config import settings
    from app.query import expand
    from app.rag.runtime.streaming import corrective as standard_stream_corrective
    from app.rag.runtime.streaming import query as standard_stream_query

    class Retriever:
        def model_copy(self, **kwargs):
            return self

    monkeypatch.setattr(settings, "ENABLE_STEP_BACK_QUERY", False)
    monkeypatch.setattr(expand, "load_base_dictionary_rules", lambda: {})
    runtime = _runtime(enable_multi_query=False, enable_hyde=False, enable_query_decomposition=False)
    await standard_stream_query.prepare_query_plan(runtime)
    runtime.data.llm = FakeListChatModel(responses=['["retry question"]'])
    monkeypatch.setattr(standard_stream_corrective, "hybrid_retriever", Retriever())
    runtime.data.corrective_second_profile = "recall50"
    runtime.data.corrective_second_enable_mq = True
    runtime.data.corrective_second_mq_count = 2
    runtime.data.score_threshold_used = 0.1
    runtime.data.retrieval_queries_base = [("main", "base query")]
    runtime.data.retriever_update = {}
    await standard_stream_corrective._prepare_retry_queries(runtime)
    assert runtime.data.multi_queries == ["retry question"]
    assert runtime.data.retry_queries == [("main", "base query"), ("mq", "retry question")]
    assert runtime.data.retry_mq_parse_meta["ok"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("response", ['["retry question"]', "[]"])
async def test_correction_updates_only_effective_query_metrics_and_keeps_the_plan(monkeypatch, response):
    from app.infrastructure.config import settings
    from app.query import expand
    from app.rag.runtime.streaming import corrective as standard_stream_corrective
    from app.rag.runtime.streaming import query as standard_stream_query

    class Retriever:
        def model_copy(self, **kwargs):
            return self

    monkeypatch.setattr(settings, "ENABLE_STEP_BACK_QUERY", False)
    monkeypatch.setattr(expand, "load_base_dictionary_rules", lambda: {})
    runtime = _runtime(enable_multi_query=False, enable_hyde=False, enable_query_decomposition=False)
    await standard_stream_query.prepare_query_plan(runtime)
    original = runtime.data.query_plan.models.multi_query
    previous = {"ok": False, "method": None, "error": "first attempt"}
    runtime.data.multi_query_elapsed = 2.0
    runtime.data.multi_query_model_used = "previous"
    runtime.data.multi_query_parse_meta = previous
    runtime.data.llm = FakeListChatModel(responses=[response])
    monkeypatch.setattr(standard_stream_corrective, "hybrid_retriever", Retriever())
    runtime.data.corrective_second_profile = "recall50"
    runtime.data.corrective_second_enable_mq = True
    runtime.data.corrective_second_mq_count = 2
    runtime.data.score_threshold_used = 0.1
    runtime.data.retrieval_queries_base = [("main", "base query")]
    runtime.data.retriever_update = {}
    await standard_stream_corrective._prepare_retry_queries(runtime)
    assert runtime.data.query_plan.models.multi_query is original
    if response == "[]":
        assert runtime.data.multi_query_parse_meta is previous
        assert runtime.data.multi_queries == []
        assert runtime.data.retry_queries == [("main", "base query")]
    else:
        assert runtime.data.multi_queries == ["retry question"]
        assert runtime.data.multi_query_elapsed >= 2.0
        assert runtime.data.multi_query_model_used == "previous"
        assert runtime.data.multi_query_parse_meta["ok"] is True
