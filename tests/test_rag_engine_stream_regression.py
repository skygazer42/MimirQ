import asyncio
import uuid
from collections.abc import AsyncGenerator, AsyncIterator
from types import SimpleNamespace

import pytest
from langchain_core.documents import Document


class _TracingRetriever:
    def __init__(self, docs: list[Document], calls: list[str]) -> None:
        self._docs = list(docs)
        self._calls = calls
        self._last_debug_metrics: dict[str, object] = {}
        self.model_copy_updates: list[dict[str, object]] = []

    def model_copy(self, *, update: object | None = None, **_kwargs: object) -> "_TracingRetriever":
        if isinstance(update, dict):
            self.model_copy_updates.append(dict(update))
        return self

    def invoke(self, _query: str) -> list[Document]:
        self._calls.append("retrieval")
        return list(self._docs)


class _QueryCapturingRetriever(_TracingRetriever):
    def __init__(self, docs: list[Document], calls: list[str]) -> None:
        super().__init__(docs, calls)
        self.queries: list[str] = []

    def invoke(self, query: str) -> list[Document]:
        self.queries.append(str(query))
        return super().invoke(query)


class _TracingChain:
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    def __or__(self, _other: object) -> "_TracingChain":
        return self

    async def astream(self, _inputs: object) -> AsyncIterator[str]:
        self._calls.append("generation")
        yield "answer"


class _BlockingGenerationChain(_TracingChain):
    def __init__(self, calls: list[str]) -> None:
        super().__init__(calls)
        self.waiting = asyncio.Event()
        self.stopped = asyncio.Event()
        self._blocker = asyncio.Event()
        self.token_stream: AsyncGenerator[str, None] | None = None

    def astream(self, _inputs: object) -> AsyncIterator[str]:
        self._calls.append("generation")
        self.token_stream = self._stream_tokens()
        return self.token_stream

    async def _stream_tokens(self) -> AsyncGenerator[str, None]:
        try:
            yield "first token"
            self.waiting.set()
            await self._blocker.wait()
        finally:
            self.stopped.set()


class _FakeChatLLM:
    model_name = "test"

    def bind(self, **_kwargs: object) -> "_FakeChatLLM":
        return self


def _mk_doc() -> Document:
    return Document(
        page_content="doc text",
        metadata={
            "document_id": "doc-1",
            "chunk_id": "chunk-1",
            "source": "source.txt",
            "score": 0.9,
            "relevance_score": 0.9,
        },
    )


def _disable_optional_features(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_MULTI_QUERY", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_HYDE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_QUERY_DECOMPOSITION", False, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_QUERY_PARALLELISM", 1, raising=False)
    monkeypatch.setattr(settings, "KG_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "KG_CHAT_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_CHUNK_INJECTION_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_QUERY_EXPANSION_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_CONTEXT_EVIDENCE_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_ABSTAIN_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_CLAIM_CHECK_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "FAITHFULNESS_SCORE_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "OUTPUT_GUARD_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "SHOW_IMAGE_IN_ANSWER", False, raising=False)
    monkeypatch.setattr(settings, "SENTENCE_CITATIONS_INLINE_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_STREAM_STATUS_EVENTS_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RAG_STREAM_RETRIEVAL_PROGRESS_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RAG_AGENTIC_MODE_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "LLM_MOCK_ENABLED", False, raising=False)


def test_active_pipeline_filter_preserves_metadata_and_selects_ready_versions() -> None:
    from app.rag.engine import RAGEngine

    active_document_id = uuid.uuid4()
    legacy_document_id = uuid.uuid4()
    pending_document_id = uuid.uuid4()
    rows = [
        (
            active_document_id,
            "processing",
            {
                "active_pipeline_ready": True,
                "active_pipeline_hash": "active-v2",
                "pipeline_hash": "pending-v3",
            },
        ),
        (legacy_document_id, "completed", {"pipeline_hash": "legacy-v1"}),
        (
            pending_document_id,
            "completed",
            {
                "active_pipeline_ready": False,
                "active_pipeline_hash": "pending-v2",
            },
        ),
    ]

    class _Query:
        def filter(self, *_args: object) -> "_Query":
            return self

        def all(self) -> list[tuple[uuid.UUID, str, dict[str, object]]]:
            return rows

    class _DB:
        def query(self, *_args: object) -> _Query:
            return _Query()

    metadata_filter = {
        "source": {"$eq": "manual"},
        "doc_pipeline_key": {"$eq": "stale-version"},
    }
    result = RAGEngine.__new__(RAGEngine)._apply_active_pipeline_metadata_filter(
        db=_DB(),
        tenant_id=uuid.uuid4(),
        document_ids=[active_document_id, legacy_document_id, pending_document_id],
        metadata_filter=metadata_filter,
    )

    assert result == {
        "source": {"$eq": "manual"},
        "doc_pipeline_key": {
            "$in": {
                f"{active_document_id}:active-v2",
                f"{legacy_document_id}:legacy-v1",
            }
        },
    }
    assert metadata_filter == {
        "source": {"$eq": "manual"},
        "doc_pipeline_key": {"$eq": "stale-version"},
    }


@pytest.mark.asyncio
async def test_stream_chat_emits_stable_event_sequence_before_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.engine as engine_mod
    from app.rag.engine import RAGEngine

    _disable_optional_features(monkeypatch)
    calls: list[str] = []
    retriever = _TracingRetriever([_mk_doc()], calls)
    monkeypatch.setattr(
        engine_mod,
        "hybrid_retriever",
        retriever,
        raising=True,
    )

    engine = RAGEngine()
    engine.prompt_template = _TracingChain(calls)
    tenant_id = uuid.uuid4()
    document_ids = [uuid.uuid4()]
    metadata_filter = {"source": {"$eq": "source.txt"}}
    scoped_metadata_filter = {
        **metadata_filter,
        "doc_pipeline_key": {"$in": {f"{document_ids[0]}:active-v2"}},
    }
    filter_calls: list[dict[str, object]] = []

    def _apply_active_pipeline_metadata_filter(**kwargs: object) -> dict[str, object]:
        filter_calls.append(dict(kwargs))
        return scoped_metadata_filter

    monkeypatch.setattr(
        engine,
        "_apply_active_pipeline_metadata_filter",
        _apply_active_pipeline_metadata_filter,
        raising=True,
    )

    def _select_llm(*_args: object, **_kwargs: object) -> tuple[_FakeChatLLM, str, str]:
        calls.append("select_llm")
        return _FakeChatLLM(), "fake", "test"

    monkeypatch.setattr(engine, "_select_llm", _select_llm, raising=True)

    stream = engine.stream_chat(
        question="What does the evidence say?",
        history=[],
        tenant_id=tenant_id,
        account_id="member-1",
        document_ids=document_ids,
        metadata_filter=metadata_filter,
        top_k=1,
        score_threshold=0.0,
        retrieval_mode="vector",
        request_id="stream-order-test",
    )

    event_types: list[str] = []
    try:
        async for event in stream:
            event_types.append(str(event.get("type")))
            if event.get("type") == "done":
                break
    finally:
        await stream.aclose()

    assert event_types[:7] == [
        "route",
        "event",
        "status",
        "event",
        "citations",
        "retrieval_info",
        "status",
    ]
    assert event_types[-2:] == ["token", "done"]
    assert calls == ["select_llm", "retrieval", "generation"]
    assert filter_calls == [
        {
            "db": None,
            "tenant_id": tenant_id,
            "document_ids": document_ids,
            "metadata_filter": metadata_filter,
        }
    ]
    assert retriever.model_copy_updates[0]["metadata_filter"] == scoped_metadata_filter


@pytest.mark.asyncio
async def test_stream_chat_propagates_retrieval_admission_timeout_before_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.engine as engine_mod
    from app.rag.engine import RAGEngine
    from app.services.rag_runtime_limiter import RetrievalAdmissionTimeoutError

    _disable_optional_features(monkeypatch)
    calls: list[str] = []
    monkeypatch.setattr(
        engine_mod,
        "hybrid_retriever",
        _TracingRetriever([_mk_doc()], calls),
        raising=True,
    )

    async def _raise_timeout(*_args: object, **_kwargs: object) -> object:
        calls.append("retrieval")
        raise RetrievalAdmissionTimeoutError(0.03)

    monkeypatch.setattr(engine_mod, "run_blocking_retrieval_call", _raise_timeout, raising=True)

    engine = RAGEngine()
    engine.prompt_template = _TracingChain(calls)

    def _select_llm(*_args: object, **_kwargs: object) -> tuple[_FakeChatLLM, str, str]:
        calls.append("select_llm")
        return _FakeChatLLM(), "fake", "test"

    monkeypatch.setattr(engine, "_select_llm", _select_llm, raising=True)

    stream = engine.stream_chat(
        question="What does the evidence say?",
        history=[],
        tenant_id=uuid.uuid4(),
        account_id="member-1",
        document_ids=[uuid.uuid4()],
        top_k=1,
        score_threshold=0.0,
        retrieval_mode="vector",
        request_id="stream-timeout-test",
    )

    try:
        with pytest.raises(RetrievalAdmissionTimeoutError):
            async for _event in stream:
                pass
    finally:
        await stream.aclose()

    assert calls == ["select_llm", "retrieval"]


@pytest.mark.asyncio
async def test_stream_chat_resolves_rewrite_bindings_through_engine_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from langchain_core.language_models.fake_chat_models import FakeListChatModel

    import app.rag.engine as engine_mod
    from app.core.config import settings
    from app.rag.engine import RAGEngine

    _disable_optional_features(monkeypatch)
    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", True, raising=False)
    monkeypatch.setattr(settings, "QUERY_REWRITE_MAX_CHARS", 400, raising=False)
    monkeypatch.setattr(engine_mod, "should_rewrite_query", lambda _q: True, raising=True)
    rewrite_spec = {
        "strategy_id": "patched-rewrite-strategy",
        "strategy_hash": "patched-rewrite-hash",
    }
    rewrite_spec_inputs: list[object] = []
    prompt_strategy_ids: list[str | None] = []

    def _build_rewrite_spec(configured_strategy: object) -> dict[str, str]:
        rewrite_spec_inputs.append(configured_strategy)
        return rewrite_spec

    def _get_rewrite_prompt(strategy_id: str | None) -> str:
        prompt_strategy_ids.append(strategy_id)
        return "History: {history}\nQuestion: {question}"

    monkeypatch.setattr(engine_mod, "build_query_rewrite_strategy_spec", _build_rewrite_spec, raising=True)
    monkeypatch.setattr(engine_mod, "get_query_rewrite_prompt_template", _get_rewrite_prompt, raising=True)

    calls: list[str] = []
    retriever = _QueryCapturingRetriever([_mk_doc()], calls)
    monkeypatch.setattr(engine_mod, "hybrid_retriever", retriever, raising=True)

    engine = RAGEngine()
    engine.models["fast"] = FakeListChatModel(responses=["rewritten evidence question"])
    monkeypatch.setattr(
        engine,
        "_select_llm",
        lambda *_args, **_kwargs: (_FakeChatLLM(), "fake", "test"),
        raising=True,
    )
    engine.prompt_template = _TracingChain(calls)

    stream = engine.stream_chat(
        question="What does the evidence say about it?",
        history=[{"role": "user", "content": "We were discussing the warranty clause."}],
        tenant_id=uuid.uuid4(),
        account_id="member-1",
        document_ids=[uuid.uuid4()],
        top_k=1,
        score_threshold=0.0,
        retrieval_mode="vector",
        request_id="stream-rewrite-test",
    )

    rewrite_event = None
    event_types: list[str] = []
    try:
        async for event in stream:
            event_types.append(str(event.get("type")))
            if event.get("type") == "rewrite":
                rewrite_event = event
            if event.get("type") == "done":
                break
    finally:
        await stream.aclose()

    assert rewrite_event is not None
    assert rewrite_event["type"] == "rewrite"
    assert rewrite_event["data"]["original"] == "What does the evidence say about it?"
    assert rewrite_event["data"]["rewritten"] == "rewritten evidence question"
    assert rewrite_event["data"]["used"] is True
    assert rewrite_event["data"]["elapsed_sec"] == pytest.approx(
        rewrite_event["data"]["elapsed_sec"],
        abs=0.1,
    )
    assert rewrite_event["data"]["model_used"] is None
    assert rewrite_event["data"]["strategy_id"] == rewrite_spec.get("strategy_id")
    assert rewrite_event["data"]["strategy_hash"] == rewrite_spec.get("strategy_hash")
    assert rewrite_spec_inputs == [getattr(settings, "QUERY_REWRITE_STRATEGY", None)]
    assert prompt_strategy_ids == ["patched-rewrite-strategy"]
    assert "rewrite" in event_types
    assert retriever.queries == ["rewritten evidence question"]


@pytest.mark.asyncio
async def test_stream_chat_resolves_prompt_template_through_engine_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from langchain_core.language_models.fake_chat_models import FakeListChatModel

    import app.rag.engine as engine_mod
    from app.rag.engine import RAGEngine

    _disable_optional_features(monkeypatch)
    prompt_template_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    chosen = SimpleNamespace(
        id=prompt_template_id,
        content="Context: {context}\nHistory: {history}\nQuestion: {question}\n{format_instructions}",
        usage_count=0,
        template_key="patched-template",
        ab_experiment_key="patched-experiment",
        ab_variant="patched-variant",
    )
    resolver_calls: list[dict[str, object]] = []

    def _resolve_prompt_template(**kwargs: object) -> SimpleNamespace:
        resolver_calls.append(dict(kwargs))
        return chosen

    monkeypatch.setattr(engine_mod, "resolve_prompt_template", _resolve_prompt_template, raising=True)

    class _DB:
        def __init__(self) -> None:
            self.commit_calls = 0

        def commit(self) -> None:
            self.commit_calls += 1

    db = _DB()
    engine = RAGEngine()
    llm = FakeListChatModel(responses=["unused"])
    monkeypatch.setattr(engine, "_select_llm", lambda *_args, **_kwargs: (llm, "fake", "test"), raising=True)

    stream = engine.stream_chat(
        question="Use the selected prompt.",
        history=[],
        tenant_id=tenant_id,
        account_id="member-1",
        document_ids=[uuid.uuid4()],
        prompt_template_id=prompt_template_id,
        request_id="stream-prompt-template-seam-test",
        db=db,
    )

    try:
        route_event = await anext(stream)
    finally:
        await stream.aclose()

    assert route_event["type"] == "route"
    assert route_event["data"]["prompt_template_id"] == str(prompt_template_id)
    assert route_event["data"]["prompt_template_key"] == "patched-template"
    assert route_event["data"]["prompt_ab_experiment_key"] == "patched-experiment"
    assert route_event["data"]["prompt_ab_variant"] == "patched-variant"
    assert resolver_calls == [
        {
            "db": db,
            "tenant_id": tenant_id,
            "prompt_template_id": prompt_template_id,
            "template_key": None,
            "ab_experiment_key": None,
            "ab_user_key": None,
        }
    ]
    assert chosen.usage_count == 1
    assert db.commit_calls == 1


@pytest.mark.asyncio
async def test_stream_chat_resolves_intent_router_through_engine_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.engine as engine_mod
    from app.core.config import settings
    from app.rag.engine import RAGEngine

    _disable_optional_features(monkeypatch)
    monkeypatch.setattr(settings, "ADAPTIVE_RETRIEVAL_ROUTING_ENABLED", False, raising=False)
    route_calls: list[dict[str, object]] = []

    def _route_retrieval_preset(**kwargs: object) -> tuple[dict[str, object], dict[str, object]]:
        route_calls.append(dict(kwargs))
        return (
            {"retrieval_mode": "vector", "top_k": 7},
            {"enabled": True, "used": True, "preset_id": "patched-router"},
        )

    monkeypatch.setattr(engine_mod, "route_retrieval_preset", _route_retrieval_preset, raising=True)
    calls: list[str] = []
    retriever = _TracingRetriever([_mk_doc()], calls)
    monkeypatch.setattr(engine_mod, "hybrid_retriever", retriever, raising=True)

    engine = RAGEngine()
    engine.prompt_template = _TracingChain(calls)
    monkeypatch.setattr(
        engine,
        "_select_llm",
        lambda *_args, **_kwargs: (_FakeChatLLM(), "fake", "test"),
        raising=True,
    )

    stream = engine.stream_chat(
        question="Route this query.",
        history=[],
        tenant_id=uuid.uuid4(),
        account_id="member-1",
        document_ids=[uuid.uuid4()],
        top_k=1,
        score_threshold=0.0,
        retrieval_mode="hybrid",
        intent_router=True,
        request_id="stream-intent-router-seam-test",
    )

    try:
        async for event in stream:
            if event.get("type") == "done":
                break
    finally:
        await stream.aclose()

    assert len(route_calls) == 1
    assert route_calls[0]["query"] == "Route this query."
    assert route_calls[0]["retrieval_mode"] == "hybrid"
    assert route_calls[0]["top_k"] == 1
    assert retriever.model_copy_updates[0]["k"] == 7
    assert retriever.model_copy_updates[0]["retrieval_mode"] == "vector"


@pytest.mark.asyncio
@pytest.mark.parametrize("termination", ["aclose", "cancel"])
async def test_stream_chat_midstream_termination_stops_generation_without_terminal_events(
    monkeypatch: pytest.MonkeyPatch,
    termination: str,
) -> None:
    import app.rag.engine as engine_mod
    from app.rag.engine import RAGEngine

    _disable_optional_features(monkeypatch)
    calls: list[str] = []
    monkeypatch.setattr(
        engine_mod,
        "hybrid_retriever",
        _TracingRetriever([_mk_doc()], calls),
        raising=True,
    )

    engine = RAGEngine()
    chain = _BlockingGenerationChain(calls)
    engine.prompt_template = chain
    monkeypatch.setattr(
        engine,
        "_select_llm",
        lambda *_args, **_kwargs: (_FakeChatLLM(), "fake", "test"),
        raising=True,
    )
    stream = engine.stream_chat(
        question="Stop after the first token.",
        history=[],
        tenant_id=uuid.uuid4(),
        account_id="member-1",
        document_ids=[uuid.uuid4()],
        top_k=1,
        score_threshold=0.0,
        retrieval_mode="vector",
        request_id=f"stream-midstream-{termination}-test",
    )

    events: list[dict[str, object]] = []
    pending: asyncio.Task[dict[str, object]] | None = None
    try:
        while True:
            event = await asyncio.wait_for(anext(stream), timeout=1)
            events.append(event)
            if event.get("type") == "token":
                break

        if termination == "aclose":
            await asyncio.wait_for(stream.aclose(), timeout=1)
        else:
            pending = asyncio.create_task(anext(stream))
            await asyncio.wait_for(chain.waiting.wait(), timeout=1)
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending

        await asyncio.wait_for(chain.stopped.wait(), timeout=1)
        assert pending is None or pending.done()
        assert not {"error", "done"}.intersection(str(event.get("type")) for event in events)
        with pytest.raises(StopAsyncIteration):
            await anext(stream)
    finally:
        if pending is not None and not pending.done():
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
        if chain.token_stream is not None:
            await chain.token_stream.aclose()
        await stream.aclose()


@pytest.mark.asyncio
async def test_alias_expansion_resolves_collaborator_through_engine_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.engine as engine_mod
    import app.rag.engine_support.standard_stream_query as query_phase
    from app.rag.engine_support.standard_stream_state import StandardStreamState

    calls: list[dict[str, object]] = []

    def _patched_alias_expansion(**kwargs: object) -> tuple[list[str], dict[str, object]]:
        calls.append(dict(kwargs))
        return ["patched alias query"], {"enabled": True, "used": True, "source": "engine"}

    def _unexpected_support_binding(**_kwargs: object) -> tuple[list[str], dict[str, object]]:
        raise AssertionError("standard stream bypassed app.rag.engine alias seam")

    monkeypatch.setattr(engine_mod, "generate_alias_queries", _patched_alias_expansion, raising=True)
    monkeypatch.setattr(query_phase, "generate_alias_queries", _unexpected_support_binding, raising=False)
    runtime = StandardStreamState(
        engine=SimpleNamespace(),
        module=engine_mod,
        payload={
            "enable_query_alias_expansion": True,
            "query_aliases": {"SSO": ["single sign-on"]},
            "query_alias_max_queries": 3,
            "query_for_retrieval": "Explain SSO",
            "enable_kg_query_expansion": False,
        },
    )

    await query_phase.expand_aliases_dictionary_and_init_kg(runtime)

    assert calls == [
        {
            "query": "Explain SSO",
            "aliases": {"SSO": ["single sign-on"]},
            "max_queries": 3,
        }
    ]
    assert runtime.data.alias_queries == ["patched alias query"]
    assert runtime.data.alias_meta["source"] == "engine"


@pytest.mark.asyncio
async def test_kg_recall_resolves_search_through_engine_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.engine as engine_mod
    import app.rag.engine_support.standard_stream_evidence as evidence_phase
    from app.core.config import settings
    from app.rag.engine_support.standard_stream_state import StandardStreamState

    monkeypatch.setattr(settings, "KG_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "KG_CHAT_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RAG_CONTEXT_MAX_KG_TOKENS", 0, raising=False)
    monkeypatch.setattr(settings, "RAG_CONTEXT_MAX_KG_CHARS", 10_000, raising=False)
    calls: list[dict[str, object]] = []

    async def _patched_kg_search(**kwargs: object) -> dict[str, object]:
        calls.append(dict(kwargs))
        return {"events": [{"title": "Patched KG event", "summary": "Runtime module result"}]}

    async def _unexpected_support_binding(**_kwargs: object) -> dict[str, object]:
        raise AssertionError("standard stream bypassed app.rag.engine KG seam")

    monkeypatch.setattr(engine_mod, "kg_search", _patched_kg_search, raising=True)
    monkeypatch.setattr(evidence_phase, "kg_search", _unexpected_support_binding, raising=False)
    tenant_id = uuid.uuid4()
    document_id = uuid.uuid4()
    runtime = StandardStreamState(
        engine=SimpleNamespace(),
        module=engine_mod,
        payload={
            "strict_visible": False,
            "kg_result_cached": None,
            "question": "What changed?",
            "tenant_id": tenant_id,
            "document_ids": [document_id],
        },
    )

    await evidence_phase.recall_kg_context(runtime)

    assert calls == [
        {
            "query": "What changed?",
            "tenant_id": tenant_id,
            "document_ids": [document_id],
        }
    ]
    assert runtime.data.kg_context == "[Event 1] Patched KG event\nRuntime module result"


@pytest.mark.asyncio
async def test_out_of_scope_guard_resolves_through_engine_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.engine as engine_mod
    import app.rag.engine_support.standard_stream_evidence as evidence_phase
    from app.core.config import settings
    from app.rag.engine_support.standard_stream_state import StandardStreamState

    monkeypatch.setattr(settings, "RAG_OUT_OF_SCOPE_LIVE_GUARD_ENABLED", True, raising=False)
    calls: list[dict[str, object]] = []

    def _patched_guard(**kwargs: object) -> dict[str, object]:
        calls.append(dict(kwargs))
        return {
            "enabled": True,
            "used": True,
            "abstain_triggered": True,
            "abstain_reason": "patched_engine_guard",
        }

    def _unexpected_support_binding(**_kwargs: object) -> dict[str, object]:
        raise AssertionError("standard stream bypassed app.rag.engine out-of-scope seam")

    monkeypatch.setattr(engine_mod, "maybe_apply_out_of_scope_live_guard", _patched_guard, raising=True)
    monkeypatch.setattr(
        evidence_phase,
        "maybe_apply_out_of_scope_live_guard",
        _unexpected_support_binding,
        raising=False,
    )
    tenant_id = uuid.uuid4()
    runtime = StandardStreamState(
        engine=SimpleNamespace(_build_retrieval_info_event=lambda **_kwargs: None),
        module=engine_mod,
        payload={
            "citations": [],
            "abstain_enabled": False,
            "abstain_triggered": False,
            "abstain_reason": None,
            "top_rel": 0.0,
            "query_for_retrieval": "Uncovered topic",
            "tenant_id": tenant_id,
            "dataset_id": None,
            "hyde_used": False,
            "hyde_text": None,
            "corrective_attempt_count": 0,
            "retrieval_queries": ["Uncovered topic"],
            "docs": [],
            "profile_norm": "",
            "corrective_attempts": [],
        },
    )

    events = [event async for event in evidence_phase.evaluate_abstention(runtime)]

    assert events == []
    assert len(calls) == 1
    assert calls[0]["query"] == "Uncovered topic"
    assert calls[0]["tenant_id"] == str(tenant_id)
    assert callable(calls[0]["verifier"])
    assert runtime.data.abstain_triggered is True
    assert runtime.data.abstain_reason == "patched_engine_guard"


@pytest.mark.asyncio
async def test_vision_helpers_resolve_through_engine_module(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.engine as engine_mod
    import app.rag.engine_support.standard_stream_generation as generation_phase
    import app.rag.engine_support.standard_stream_retrieval as retrieval_phase
    from app.core.config import settings
    from app.rag.engine_support.standard_stream_state import StandardStreamState

    monkeypatch.setattr(settings, "VISION_RAG_READER_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "VISION_LLM_ENABLED", False, raising=False)
    reader_calls: list[dict[str, object]] = []

    async def _patched_reader(**kwargs: object) -> tuple[list[Document], dict[str, object]]:
        reader_calls.append(dict(kwargs))
        return [Document(page_content="vision text", metadata={"source": "patched-reader"})], {
            "enabled": True,
            "used": True,
            "source": "engine",
        }

    async def _unexpected_reader(**_kwargs: object) -> tuple[list[Document], dict[str, object]]:
        raise AssertionError("standard stream bypassed app.rag.engine vision reader seam")

    monkeypatch.setattr(engine_mod, "build_vision_reader_context_docs", _patched_reader, raising=True)
    monkeypatch.setattr(
        retrieval_phase,
        "build_vision_reader_context_docs",
        _unexpected_reader,
        raising=False,
    )
    tenant_id = uuid.uuid4()
    image_doc = Document(page_content="image", metadata={"source": "image.png"})
    runtime = StandardStreamState(
        engine=SimpleNamespace(http_async_client=object()),
        module=engine_mod,
        payload={
            "image_docs": [image_doc],
            "question": "Read the image",
            "tenant_id": tenant_id,
            "docs": [],
        },
    )

    reader_events = [event async for event in retrieval_phase.read_images_and_initialize_tag(runtime)]

    assert reader_events == []
    assert reader_calls[0]["image_docs"] == [image_doc]
    assert runtime.data.vision_reader_meta["source"] == "engine"
    assert runtime.data.docs[0].page_content == "vision text"

    monkeypatch.setattr(settings, "VISION_RAG_GENERATION_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "VISION_LLM_ENABLED", True, raising=False)
    block_calls: list[dict[str, object]] = []
    stream_calls: list[dict[str, object]] = []
    token_stream_marker = object()

    async def _patched_blocks(**kwargs: object) -> tuple[list[dict[str, object]], dict[str, object]]:
        block_calls.append(dict(kwargs))
        return [{"type": "image_url", "image_url": {"url": "data:image/png;base64,AA=="}}], {"loaded": 1}

    def _patched_stream(**kwargs: object) -> object:
        stream_calls.append(dict(kwargs))
        return token_stream_marker

    async def _unexpected_blocks(**_kwargs: object) -> tuple[list[dict[str, object]], dict[str, object]]:
        raise AssertionError("standard stream bypassed app.rag.engine vision block seam")

    def _unexpected_stream(**_kwargs: object) -> object:
        raise AssertionError("standard stream bypassed app.rag.engine vision stream seam")

    monkeypatch.setattr(engine_mod, "build_vision_image_blocks", _patched_blocks, raising=True)
    monkeypatch.setattr(engine_mod, "stream_vision_chat_completions_tokens", _patched_stream, raising=True)
    monkeypatch.setattr(generation_phase, "build_vision_image_blocks", _unexpected_blocks, raising=False)
    monkeypatch.setattr(
        generation_phase,
        "stream_vision_chat_completions_tokens",
        _unexpected_stream,
        raising=False,
    )
    runtime.data.source_identification_answer_used = False
    runtime.data.multimodal_modality = "image"
    runtime.data.current_prompt_template = SimpleNamespace(
        format_messages=lambda **_kwargs: [SimpleNamespace(type="human", content="Read the image")]
    )
    runtime.data.generation_inputs = {}
    runtime.data.token_stream = None

    await generation_phase.prepare_vision_generation(runtime)

    assert block_calls[0]["image_docs"] == [image_doc]
    assert stream_calls[0]["http_client"] is runtime.engine.http_async_client
    assert runtime.data.vision_generation_meta["used"] is True
    assert runtime.data.token_stream is token_stream_marker
