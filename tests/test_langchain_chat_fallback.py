from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any

import httpx
import pytest
from langchain_core.documents import Document
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, SystemMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import ConfigDict, Field


class _SequentialRetriever:
    def __init__(self, docs_by_call: list[list[Document]]) -> None:
        self._docs_by_call = [list(items) for items in docs_by_call]
        self._call_index = 0
        self._last_debug_metrics: dict[str, object] = {}

    def model_copy(self, *, update=None, **_kwargs):  # noqa: ANN001
        _ = update
        return self

    def invoke(self, _query: str) -> list[Document]:
        idx = min(self._call_index, len(self._docs_by_call) - 1)
        self._call_index += 1
        return list(self._docs_by_call[idx])


def _mk_doc(*, doc_id: str, chunk_index: int, score: float = 0.95) -> Document:
    chunk_id = f"{doc_id}:{chunk_index}"
    return Document(
        page_content=f"{chunk_id} content with evidence",
        id=chunk_id,
        metadata={
            "document_id": doc_id,
            "chunk_id": chunk_id,
            "chunk_index": int(chunk_index),
            "source": "doc.txt",
            "page": 1,
            "score": float(score),
            "relevance_score": float(score),
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
    monkeypatch.setattr(settings, "RAG_ABSTAIN_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RAG_ABSTAIN_MIN_CITATIONS", 1, raising=False)
    monkeypatch.setattr(settings, "RAG_ABSTAIN_MIN_TOP_RELEVANCE_SCORE", 0.0, raising=False)
    monkeypatch.setattr(settings, "LLM_MOCK_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "LLM_API_KEY", "test-key", raising=False)


class _StubChatModel(BaseChatModel):
    name: str
    response_text: str = ""
    stream_chunks: list[str] = Field(default_factory=list)
    stream_exc: Exception | None = None
    payload_meta: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(arbitrary_types_allowed=True)

    @property
    def _llm_type(self) -> str:
        return "stub_chat_model"

    @property
    def model_name(self) -> str:
        return self.name

    def get_last_payload_meta(self) -> dict[str, Any]:
        return dict(self.payload_meta)

    def _generate(
        self,
        messages: list,  # noqa: ANN001
        stop: list[str] | None = None,
        run_manager=None,  # noqa: ANN001
        **kwargs: Any,
    ) -> ChatResult:
        _ = (messages, stop, run_manager, kwargs)
        if self.stream_exc is not None:
            raise self.stream_exc
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=self.response_text))])

    async def _agenerate(
        self,
        messages: list,  # noqa: ANN001
        stop: list[str] | None = None,
        run_manager=None,  # noqa: ANN001
        **kwargs: Any,
    ) -> ChatResult:
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    def _stream(
        self,
        messages: list,  # noqa: ANN001
        stop: list[str] | None = None,
        run_manager=None,  # noqa: ANN001
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        _ = (messages, stop, run_manager, kwargs)
        if self.stream_exc is not None:
            raise self.stream_exc
        for chunk in self.stream_chunks:
            yield ChatGenerationChunk(message=AIMessageChunk(content=chunk))

    async def _astream(
        self,
        messages: list,  # noqa: ANN001
        stop: list[str] | None = None,
        run_manager=None,  # noqa: ANN001
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        _ = (messages, stop, run_manager, kwargs)
        if self.stream_exc is not None:
            raise self.stream_exc
        for chunk in self.stream_chunks:
            yield ChatGenerationChunk(message=AIMessageChunk(content=chunk))


def test_prompt_cache_chat_openai_injects_cache_control_for_anthropic_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import settings
    from app.rag.llm.langchain_chat import PromptCacheChatOpenAI

    monkeypatch.setattr(settings, "PROMPT_CACHE_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "PROMPT_CACHE_MIN_CHARS", 10, raising=False)

    model = PromptCacheChatOpenAI(
        model="claude-3-5-haiku",
        api_key="k",
        base_url="https://anthropic.example/v1",
        streaming=True,
    )

    payload = model._get_request_payload(
        [
            SystemMessage(content="system prompt"),
            HumanMessage(content="01234567890"),
        ]
    )

    messages = payload.get("messages") or []
    assert messages[0]["content"][0]["cache_control"]["type"] == "ephemeral"
    assert messages[1]["content"][0]["cache_control"]["type"] == "ephemeral"


def test_build_chat_model_from_config_skips_pooled_async_client_by_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import settings
    from app.rag.llm import langchain_chat as lc_mod

    captured: list[dict[str, Any]] = []

    class _FakePromptCacheChatOpenAI:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            _ = args
            captured.append(dict(kwargs))

    monkeypatch.setattr(lc_mod, "PromptCacheChatOpenAI", _FakePromptCacheChatOpenAI, raising=True)
    monkeypatch.setattr(settings, "LLM_FALLBACK_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "LLM_USE_POOLED_ASYNC_HTTP_CLIENT", False, raising=False)

    model = lc_mod.build_chat_model_from_config(
        model_config={"model": "demo-model", "api_key": "k", "base_url": "https://example.com/v1"},
        http_client="sync-client",
        http_async_client="async-client",
        streaming=True,
    )

    assert isinstance(model, _FakePromptCacheChatOpenAI)
    assert captured[0]["http_client"] == "sync-client"
    assert "http_async_client" not in captured[0]


def test_build_chat_model_from_config_can_opt_into_pooled_async_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import settings
    from app.rag.llm import langchain_chat as lc_mod

    captured: list[dict[str, Any]] = []

    class _FakePromptCacheChatOpenAI:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            _ = args
            captured.append(dict(kwargs))

    monkeypatch.setattr(lc_mod, "PromptCacheChatOpenAI", _FakePromptCacheChatOpenAI, raising=True)
    monkeypatch.setattr(settings, "LLM_FALLBACK_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "LLM_USE_POOLED_ASYNC_HTTP_CLIENT", True, raising=False)

    model = lc_mod.build_chat_model_from_config(
        model_config={"model": "demo-model", "api_key": "k", "base_url": "https://example.com/v1"},
        http_client="sync-client",
        http_async_client="async-client",
        streaming=True,
    )

    assert isinstance(model, _FakePromptCacheChatOpenAI)
    assert captured[0]["http_client"] == "sync-client"
    assert captured[0]["http_async_client"] == "async-client"


@pytest.mark.asyncio
async def test_fallback_chat_openai_streams_from_backup_on_retryable_startup_failure() -> None:
    from app.rag.llm.langchain_chat import FallbackChatOpenAI

    primary = _StubChatModel(
        name="primary-model",
        stream_exc=httpx.ConnectError("primary down"),
        payload_meta={"prompt_cache_applied": False, "prompt_cache_message_count": 0},
    )
    backup = _StubChatModel(
        name="backup-model",
        stream_chunks=["backup ", "answer"],
        payload_meta={"prompt_cache_applied": True, "prompt_cache_message_count": 2},
    )
    llm = FallbackChatOpenAI(primary=primary, fallbacks=[backup])

    parts: list[str] = []
    async for chunk in llm.astream([HumanMessage(content="hello")]):
        if chunk.content:
            parts.append(str(chunk.content))

    assert "".join(parts) == "backup answer"
    meta = llm.get_last_invocation_meta()
    assert meta.get("fallback_used") is True
    assert meta.get("selected_model") == "backup-model"
    assert meta.get("failure_count") == 1
    assert meta.get("prompt_cache_applied") is True


@pytest.mark.asyncio
async def test_fallback_chat_openai_raises_when_all_retryable_providers_fail() -> None:
    from app.rag.llm.fallback import AllProvidersFailedError
    from app.rag.llm.langchain_chat import FallbackChatOpenAI

    timeout_exc = httpx.TimeoutException("timeout")
    llm = FallbackChatOpenAI(
        primary=_StubChatModel(name="primary-model", stream_exc=timeout_exc),
        fallbacks=[_StubChatModel(name="backup-model", stream_exc=timeout_exc)],
    )

    with pytest.raises(AllProvidersFailedError):
        async for _chunk in llm.astream([HumanMessage(content="hello")]):
            pass


@pytest.mark.asyncio
async def test_stream_chat_surfaces_llm_fallback_and_prompt_cache_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.engine as engine_mod
    from app.rag.engine import RAGEngine

    _disable_optional_features(monkeypatch)
    retriever = _SequentialRetriever(docs_by_call=[[_mk_doc(doc_id="doc-a", chunk_index=0)]])
    monkeypatch.setattr(engine_mod, "hybrid_retriever", retriever, raising=True)

    def _fake_build_llm(self, _chat_cls, model_name: str):  # noqa: ANN001
        return FallbackChatOpenAI(
            primary=_StubChatModel(name=f"{model_name}-primary", stream_exc=httpx.ConnectError("primary down")),
            fallbacks=[
                _StubChatModel(
                    name="backup-model",
                    stream_chunks=["backup answer"],
                    payload_meta={"prompt_cache_applied": True, "prompt_cache_message_count": 2},
                )
            ],
        )

    from app.rag.llm.langchain_chat import FallbackChatOpenAI

    monkeypatch.setattr(RAGEngine, "_build_llm", _fake_build_llm, raising=True)

    engine = RAGEngine()
    done_event = None
    token_parts: list[str] = []

    agen = engine.stream_chat(
        question="What does the evidence say?",
        history=[],
        tenant_id=uuid.uuid4(),
        account_id="u",
        document_ids=[uuid.uuid4()],
        top_k=2,
        score_threshold=0.0,
        retrieval_mode="vector",
        request_id="llm-fallback-metrics-test",
    )

    try:
        async for event in agen:
            if event.get("type") == "token":
                token_parts.append(str((event.get("data") or {}).get("content") or ""))
            if event.get("type") == "done":
                done_event = event
                break
    finally:
        await agen.aclose()

    assert "".join(token_parts) == "backup answer"
    assert done_event is not None
    assert (done_event.get("data") or {}).get("model_used") == "backup-model"

    metrics = ((done_event.get("data") or {}).get("metrics") or {})
    assert metrics.get("llm_provider_fallback_used") is True
    assert metrics.get("llm_provider_fallback_target") == "backup-model"
    assert metrics.get("llm_provider_fallback_failures") == 1
    assert metrics.get("llm_prompt_cache_applied") is True
    assert metrics.get("llm_prompt_cache_message_count") == 2
