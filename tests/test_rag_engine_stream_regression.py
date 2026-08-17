import uuid
from collections.abc import AsyncIterator

import pytest
from langchain_core.documents import Document


class _TracingRetriever:
    def __init__(self, docs: list[Document], calls: list[str]) -> None:
        self._docs = list(docs)
        self._calls = calls
        self._last_debug_metrics: dict[str, object] = {}

    def model_copy(self, *, update: object | None = None, **_kwargs: object) -> "_TracingRetriever":
        return self

    def invoke(self, _query: str) -> list[Document]:
        self._calls.append("retrieval")
        return list(self._docs)


class _TracingChain:
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    def __or__(self, _other: object) -> "_TracingChain":
        return self

    async def astream(self, _inputs: object) -> AsyncIterator[str]:
        self._calls.append("generation")
        yield "answer"


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


@pytest.mark.asyncio
async def test_stream_chat_emits_stable_event_sequence_before_generation(
    monkeypatch: pytest.MonkeyPatch,
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
