from __future__ import annotations

import json

import httpx
import pytest

from app.core.config import settings
from app.rag.embedding.providers.ollama import OllamaEmbedding


@pytest.mark.asyncio
async def test_ollama_embedding_encode_uses_pooled_http_client_and_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content.decode("utf-8")))
        # First request fails -> triggers retry.
        if len(calls) == 1:
            return httpx.Response(500, json={"error": "boom"})
        return httpx.Response(200, json={"embeddings": [[0.1, 0.2, 0.3]]})

    transport = httpx.MockTransport(handler)
    sync_client = httpx.Client(transport=transport)
    async_client = httpx.AsyncClient(transport=transport)

    class _Pool:
        def get_external_sync_client(self) -> httpx.Client:
            return sync_client

        def get_external_async_client(self) -> httpx.AsyncClient:
            return async_client

    import app.rag.embedding.providers.ollama as ollama_module

    monkeypatch.setattr(ollama_module, "get_http_client_pool", lambda: _Pool(), raising=True)

    # Guard against falling back to non-pooled clients.
    import requests

    monkeypatch.setattr(
        requests,
        "post",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("requests.post should not be used")),
        raising=True,
    )
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("httpx.AsyncClient should not be instantiated")),
        raising=True,
    )

    monkeypatch.setattr(settings, "EMBEDDING_API_TIMEOUT_SEC", 0.1, raising=False)
    monkeypatch.setattr(settings, "EMBEDDING_API_MAX_RETRIES", 1, raising=False)
    monkeypatch.setattr(settings, "EMBEDDING_API_RETRY_BACKOFF_SEC", 0.0, raising=False)
    monkeypatch.setattr(settings, "EMBEDDING_API_RETRY_JITTER_SEC", 0.0, raising=False)
    monkeypatch.setattr(settings, "EMBEDDING_API_BATCH_SIZE", 64, raising=False)

    model = OllamaEmbedding(
        model="bge-m3", dimension=3, base_url="http://ollama/api/embed", api_key="no_api_key"
    )
    out = model.encode("hi")

    assert out == [[0.1, 0.2, 0.3]]
    assert len(calls) == 2
    assert calls[0]["model"] == "bge-m3"
    assert calls[0]["input"] == ["hi"]

    await async_client.aclose()
    sync_client.close()


@pytest.mark.asyncio
async def test_ollama_embedding_aencode_uses_pooled_http_client_and_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(json.loads(request.content.decode("utf-8")))
        if len(calls) == 1:
            return httpx.Response(502, json={"error": "bad gateway"})
        return httpx.Response(200, json={"embeddings": [[0.1, 0.2, 0.3]]})

    transport = httpx.MockTransport(handler)
    sync_client = httpx.Client(transport=transport)
    async_client = httpx.AsyncClient(transport=transport)

    class _Pool:
        def get_external_sync_client(self) -> httpx.Client:
            return sync_client

        def get_external_async_client(self) -> httpx.AsyncClient:
            return async_client

    import app.rag.embedding.providers.ollama as ollama_module

    monkeypatch.setattr(ollama_module, "get_http_client_pool", lambda: _Pool(), raising=True)

    # Guard against instantiating a new AsyncClient in provider code.
    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("httpx.AsyncClient should not be instantiated")),
        raising=True,
    )

    monkeypatch.setattr(settings, "EMBEDDING_API_TIMEOUT_SEC", 0.1, raising=False)
    monkeypatch.setattr(settings, "EMBEDDING_API_MAX_RETRIES", 1, raising=False)
    monkeypatch.setattr(settings, "EMBEDDING_API_RETRY_BACKOFF_SEC", 0.0, raising=False)
    monkeypatch.setattr(settings, "EMBEDDING_API_RETRY_JITTER_SEC", 0.0, raising=False)
    monkeypatch.setattr(settings, "EMBEDDING_API_BATCH_SIZE", 64, raising=False)

    model = OllamaEmbedding(
        model="bge-m3", dimension=3, base_url="http://ollama/api/embed", api_key="no_api_key"
    )
    out = await model.aencode("hi")

    assert out == [[0.1, 0.2, 0.3]]
    assert len(calls) == 2

    await async_client.aclose()
    sync_client.close()


@pytest.mark.asyncio
async def test_ollama_embedding_validates_vector_dimension(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"embeddings": [[0.1, 0.2]]})

    transport = httpx.MockTransport(handler)
    sync_client = httpx.Client(transport=transport)
    async_client = httpx.AsyncClient(transport=transport)

    class _Pool:
        def get_external_sync_client(self) -> httpx.Client:
            return sync_client

        def get_external_async_client(self) -> httpx.AsyncClient:
            return async_client

    import app.rag.embedding.providers.ollama as ollama_module

    monkeypatch.setattr(ollama_module, "get_http_client_pool", lambda: _Pool(), raising=True)
    monkeypatch.setattr(settings, "EMBEDDING_API_TIMEOUT_SEC", 0.1, raising=False)
    monkeypatch.setattr(settings, "EMBEDDING_API_MAX_RETRIES", 0, raising=False)
    monkeypatch.setattr(settings, "EMBEDDING_API_BATCH_SIZE", 64, raising=False)

    model = OllamaEmbedding(
        model="bge-m3", dimension=3, base_url="http://ollama/api/embed", api_key="no_api_key"
    )
    with pytest.raises(ValueError, match="dimension"):
        model.encode("hi")

    await async_client.aclose()
    sync_client.close()

