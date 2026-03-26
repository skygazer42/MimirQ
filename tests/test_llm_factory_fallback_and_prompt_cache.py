from __future__ import annotations

import httpx
import pytest

from app.core.config import settings
from app.rag.llm.base import BaseLLMClient
from app.rag.llm.fallback import AllProvidersFailedError, FallbackLLMClient
from app.rag.llm.models import LLMMessage, LLMResponse, LLMRole


class _DummyClient(BaseLLMClient):
    def __init__(
        self,
        *,
        response: str = "ok",
        chat_exc: Exception | None = None,
        stream_exc: Exception | None = None,
    ) -> None:
        self._response = response
        self._chat_exc = chat_exc
        self._stream_exc = stream_exc

    async def chat(
        self,
        messages: list[LLMMessage],
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: object,
    ) -> LLMResponse:
        _ = messages
        _ = temperature
        _ = max_tokens
        _ = kwargs
        if self._chat_exc is not None:
            raise self._chat_exc
        return LLMResponse(content=self._response)

    def chat_stream(
        self,
        messages: list[LLMMessage],
        temperature: float | None = None,
        max_tokens: int | None = None,
        include_reasoning: bool = False,
        **kwargs: object,
    ):
        _ = messages
        _ = temperature
        _ = max_tokens
        _ = include_reasoning
        _ = kwargs

        async def _gen():
            if self._stream_exc is not None:
                raise self._stream_exc
            yield self._response, None

        return _gen()


class _ScriptedStreamClient(BaseLLMClient):
    def __init__(
        self,
        *,
        chunks: list[str] | None = None,
        exc_before_first_chunk: Exception | None = None,
        exc_after_chunks: Exception | None = None,
    ) -> None:
        self._chunks = list(chunks or [])
        self._exc_before_first_chunk = exc_before_first_chunk
        self._exc_after_chunks = exc_after_chunks

    async def chat(
        self,
        messages: list[LLMMessage],
        temperature: float | None = None,
        max_tokens: int | None = None,
        **kwargs: object,
    ) -> LLMResponse:
        _ = messages
        _ = temperature
        _ = max_tokens
        _ = kwargs
        return LLMResponse(content="unused")

    def chat_stream(
        self,
        messages: list[LLMMessage],
        temperature: float | None = None,
        max_tokens: int | None = None,
        include_reasoning: bool = False,
        **kwargs: object,
    ):
        _ = messages
        _ = temperature
        _ = max_tokens
        _ = include_reasoning
        _ = kwargs

        async def _gen():
            if self._exc_before_first_chunk is not None:
                raise self._exc_before_first_chunk
            for chunk in self._chunks:
                yield chunk, None
            if self._exc_after_chunks is not None:
                raise self._exc_after_chunks

        return _gen()


def test_parse_fallback_specs_supports_json_and_csv() -> None:
    from app.rag.llm.factory import _parse_fallback_specs

    assert _parse_fallback_specs("gpt-4o-mini, claude-3-haiku") == [
        {"model": "gpt-4o-mini"},
        {"model": "claude-3-haiku"},
    ]
    assert _parse_fallback_specs('[{"model":"m1"},{"model":"m2","base_url":"https://x"}]') == [
        {"model": "m1"},
        {"model": "m2", "base_url": "https://x"},
    ]


@pytest.mark.asyncio
async def test_create_llm_client_returns_fallback_wrapper_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.rag.llm import factory as factory_mod

    created_configs: list[dict[str, object] | None] = []

    def _fake_ctor(*, model_config=None):
        created_configs.append(dict(model_config or {}))
        model = str((model_config or {}).get("model") or "")
        if model == "bad-model":
            raise RuntimeError("init failed")
        return _DummyClient(response=model or "primary")

    monkeypatch.setattr(factory_mod, "OpenAIChatClient", _fake_ctor, raising=True)
    monkeypatch.setattr(settings, "LLM_FALLBACK_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "LLM_FALLBACK_MODELS", "bad-model, backup-a, backup-b", raising=False)

    client = await factory_mod.create_llm_client(model_config={"model": "primary", "api_key": "k"})
    assert isinstance(client, FallbackLLMClient)
    assert len(client._clients) == 3  # primary + two successful backups
    assert created_configs[0] == {"model": "primary", "api_key": "k"}
    assert created_configs[1]["model"] == "bad-model"
    assert created_configs[2]["model"] == "backup-a"
    assert created_configs[3]["model"] == "backup-b"


@pytest.mark.asyncio
async def test_create_llm_client_keeps_existing_behavior_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.rag.llm import factory as factory_mod

    def _fake_ctor(*, model_config=None):
        _ = model_config
        return _DummyClient(response="primary")

    monkeypatch.setattr(factory_mod, "OpenAIChatClient", _fake_ctor, raising=True)
    monkeypatch.setattr(settings, "LLM_FALLBACK_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "LLM_FALLBACK_MODELS", "backup-a", raising=False)

    client = await factory_mod.create_llm_client(model_config={"model": "primary"})
    assert isinstance(client, _DummyClient)


@pytest.mark.asyncio
async def test_fallback_client_retries_retryable_errors_for_chat() -> None:
    timeout_exc = httpx.TimeoutException("timeout")
    chain = FallbackLLMClient(
        [
            _DummyClient(chat_exc=timeout_exc),
            _DummyClient(response="from-backup"),
        ]
    )
    out = await chain.chat([LLMMessage(role=LLMRole.USER, content="hello")])
    assert out.content == "from-backup"


@pytest.mark.asyncio
async def test_fallback_client_raises_when_all_retryable_fail() -> None:
    timeout_exc = httpx.TimeoutException("timeout")
    chain = FallbackLLMClient([_DummyClient(chat_exc=timeout_exc), _DummyClient(chat_exc=timeout_exc)])
    with pytest.raises(AllProvidersFailedError):
        await chain.chat([LLMMessage(role=LLMRole.USER, content="hello")])


@pytest.mark.asyncio
async def test_fallback_client_does_not_swallow_non_retryable_errors() -> None:
    chain = FallbackLLMClient(
        [
            _DummyClient(chat_exc=ValueError("bad prompt")),
            _DummyClient(response="should-not-be-used"),
        ]
    )
    with pytest.raises(ValueError, match="bad prompt"):
        await chain.chat([LLMMessage(role=LLMRole.USER, content="hello")])


def test_prompt_cache_annotation_only_for_anthropic_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.rag.llm.factory import OpenAIChatClient

    client = OpenAIChatClient.__new__(OpenAIChatClient)
    client._is_anthropic_compatible = True
    monkeypatch.setattr(settings, "PROMPT_CACHE_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "PROMPT_CACHE_MIN_CHARS", 10, raising=False)

    converted = client._convert_messages(
        [
            LLMMessage(role=LLMRole.SYSTEM, content="sys"),
            LLMMessage(role=LLMRole.USER, content="01234567890"),
        ]
    )
    first_content = converted[0].content
    second_content = converted[1].content
    assert isinstance(first_content, list)
    assert first_content[0]["cache_control"]["type"] == "ephemeral"
    assert isinstance(second_content, list)
    assert second_content[0]["cache_control"]["type"] == "ephemeral"


def test_prompt_cache_is_skipped_for_non_anthropic_or_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.rag.llm.factory import OpenAIChatClient

    client = OpenAIChatClient.__new__(OpenAIChatClient)
    client._is_anthropic_compatible = False
    monkeypatch.setattr(settings, "PROMPT_CACHE_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "PROMPT_CACHE_MIN_CHARS", 1, raising=False)

    converted = client._convert_messages([LLMMessage(role=LLMRole.USER, content="hello")])
    assert converted[0].content == "hello"


@pytest.mark.asyncio
async def test_fallback_client_chat_stream_retries_before_first_chunk() -> None:
    timeout_exc = httpx.TimeoutException("timeout")
    chain = FallbackLLMClient(
        [
            _ScriptedStreamClient(exc_before_first_chunk=timeout_exc),
            _ScriptedStreamClient(chunks=["from-backup"]),
        ]
    )

    chunks = [chunk async for chunk in chain.chat_stream([LLMMessage(role=LLMRole.USER, content="hello")])]
    assert chunks == [("from-backup", None)]


@pytest.mark.asyncio
async def test_fallback_client_chat_stream_raises_after_partial_output() -> None:
    timeout_exc = httpx.TimeoutException("timeout")
    chain = FallbackLLMClient(
        [
            _ScriptedStreamClient(chunks=["partial"], exc_after_chunks=timeout_exc),
            _ScriptedStreamClient(chunks=["should-not-appear"]),
        ]
    )

    chunks: list[tuple[str, str | None]] = []
    with pytest.raises(httpx.TimeoutException, match="timeout"):
        async for chunk in chain.chat_stream([LLMMessage(role=LLMRole.USER, content="hello")]):
            chunks.append(chunk)

    assert chunks == [("partial", None)]
