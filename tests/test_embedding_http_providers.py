import asyncio
import gc
import weakref
from types import SimpleNamespace
from typing import Any

import httpx
import pytest


class _SyncClient:
    def __init__(self, responses: list[httpx.Response | Exception]) -> None:
        self._responses = iter(responses)
        self.calls: list[dict[str, Any]] = []

    def post(self, url: str, **kwargs: Any) -> httpx.Response:
        self.calls.append({"url": url, **kwargs})
        response = next(self._responses)
        if isinstance(response, Exception):
            raise response
        return response


class _AsyncClient:
    def __init__(self, responses: list[httpx.Response | Exception]) -> None:
        self._responses = iter(responses)
        self.calls: list[dict[str, Any]] = []

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        self.calls.append({"url": url, **kwargs})
        response = next(self._responses)
        if isinstance(response, Exception):
            raise response
        return response


def _response(url: str, status: int, payload: dict[str, Any]) -> httpx.Response:
    headers = {"Retry-After": "0"} if status == 429 else None
    return httpx.Response(
        status,
        headers=headers,
        json=payload,
        request=httpx.Request("POST", url),
    )


def _configure_retry_settings(monkeypatch: pytest.MonkeyPatch, module: Any) -> None:
    monkeypatch.setattr(module.settings, "EMBEDDING_API_MAX_RETRIES", 1, raising=False)
    monkeypatch.setattr(module.settings, "EMBEDDING_API_RETRY_BACKOFF_SEC", 0, raising=False)
    monkeypatch.setattr(module.settings, "EMBEDDING_API_RETRY_JITTER_SEC", 0, raising=False)
    monkeypatch.setattr(module.settings, "EMBEDDING_API_MAX_CONCURRENCY", 2, raising=False)


@pytest.mark.asyncio
async def test_openai_embedding_retries_sync_and_async_429(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.embedding.providers.openai as provider_module

    url = "https://embedding.example/v1/embeddings"
    error = {"error": "busy"}
    success = {"data": [{"embedding": [1.0, 2.0]}]}
    sync_client = _SyncClient([_response(url, 429, error), _response(url, 200, success)])
    async_client = _AsyncClient([_response(url, 429, error), _response(url, 200, success)])
    pool = SimpleNamespace(
        get_external_sync_client=lambda: sync_client,
        get_external_async_client=lambda: async_client,
    )
    monkeypatch.setattr(provider_module, "get_http_client_pool", lambda: pool)
    _configure_retry_settings(monkeypatch, provider_module)

    embedding = provider_module.OpenAICompatibleEmbedding(
        model="embed-model",
        api_key="test-key",
        base_url=url,
    )

    assert embedding.encode(["sync"]) == [[1.0, 2.0]]
    assert await embedding.aencode(["async"]) == [[1.0, 2.0]]
    assert len(sync_client.calls) == 2
    assert len(async_client.calls) == 2
    assert sync_client.calls[0]["headers"]["Authorization"] == "Bearer test-key"
    assert async_client.calls[0]["headers"]["Authorization"] == "Bearer test-key"


@pytest.mark.asyncio
async def test_ollama_embedding_retries_sync_and_async_429(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.embedding.providers.ollama as provider_module

    url = "http://ollama.example/api/embed"
    error = {"error": "busy"}
    success = {"embeddings": [[3.0, 4.0]]}
    sync_client = _SyncClient([_response(url, 429, error), _response(url, 200, success)])
    async_client = _AsyncClient([_response(url, 429, error), _response(url, 200, success)])
    pool = SimpleNamespace(
        get_external_sync_client=lambda: sync_client,
        get_external_async_client=lambda: async_client,
    )
    monkeypatch.setattr(provider_module, "get_http_client_pool", lambda: pool)
    _configure_retry_settings(monkeypatch, provider_module)

    embedding = provider_module.OllamaEmbedding(
        model="embed-model",
        dimension=2,
        base_url=url,
    )

    assert embedding.encode(["sync"]) == [[3.0, 4.0]]
    assert await embedding.aencode(["async"]) == [[3.0, 4.0]]
    assert len(sync_client.calls) == 2
    assert len(async_client.calls) == 2
    assert "headers" not in sync_client.calls[0]
    assert "headers" not in async_client.calls[0]


@pytest.mark.asyncio
async def test_openai_embedding_retries_sync_and_async_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.embedding.providers.openai as provider_module

    url = "https://embedding.example/v1/embeddings"
    success = {"data": [{"embedding": [5.0, 6.0]}]}
    sync_client = _SyncClient(
        [
            httpx.ReadTimeout("timed out", request=httpx.Request("POST", url)),
            _response(url, 200, success),
        ]
    )
    async_client = _AsyncClient(
        [
            httpx.ReadTimeout("timed out", request=httpx.Request("POST", url)),
            _response(url, 200, success),
        ]
    )
    pool = SimpleNamespace(
        get_external_sync_client=lambda: sync_client,
        get_external_async_client=lambda: async_client,
    )
    monkeypatch.setattr(provider_module, "get_http_client_pool", lambda: pool)
    _configure_retry_settings(monkeypatch, provider_module)

    embedding = provider_module.OpenAICompatibleEmbedding(
        model="embed-model",
        base_url=url,
    )

    assert embedding.encode(["sync"]) == [[5.0, 6.0]]
    assert await embedding.aencode(["async"]) == [[5.0, 6.0]]
    assert len(sync_client.calls) == 2
    assert len(async_client.calls) == 2


def test_async_embedding_semaphore_pool_does_not_retain_closed_loops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.embedding.providers._embedding_http as http_module

    monkeypatch.setattr(http_module.settings, "EMBEDDING_API_MAX_CONCURRENCY", 2, raising=False)
    pool = http_module.EmbeddingHTTPConcurrency("test embedding")
    loop_refs: list[weakref.ReferenceType[asyncio.AbstractEventLoop]] = []

    async def touch_pool() -> None:
        first = pool.async_semaphore()
        second = pool.async_semaphore()
        assert first is second
        await first.acquire()
        await first.acquire()
        waiter = asyncio.create_task(first.acquire())
        await asyncio.sleep(0)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        first.release()
        first.release()

    for _ in range(20):
        loop = asyncio.new_event_loop()
        loop.run_until_complete(touch_pool())
        loop_refs.append(weakref.ref(loop))
        loop.close()
        del loop

    gc.collect()

    assert all(loop_ref() is None for loop_ref in loop_refs)
    assert pool.async_pool_size == 0
