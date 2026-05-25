from __future__ import annotations

import pytest

from tests.helpers.async_utils import yield_control
from tests.helpers.outbound_http_assertions import assert_no_internal_context_headers


class _DummyResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload
        self.status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self):  # noqa: ANN201
        return self._payload


class _DummySyncClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def post(self, url: str, *, json: dict, headers: dict, timeout: float | None = None):  # noqa: ANN201
        self.calls.append((url, dict(headers)))
        return _DummyResponse({"data": [{"embedding": [0.1, 0.2]}]})


class _DummyAsyncClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def post(self, url: str, *, json: dict, headers: dict, timeout: float | None = None):  # noqa: ANN201
        await yield_control()
        self.calls.append((url, dict(headers)))
        return _DummyResponse({"data": [{"embedding": [0.1, 0.2]}]})


def test_openai_embedding_encode_uses_external_pool_not_requests(monkeypatch):
    import requests

    import app.rag.embedding.providers.openai as provider

    spy = {"requests_post": 0}

    def _requests_post(*_args, **_kwargs):  # noqa: ANN001
        spy["requests_post"] += 1
        return _DummyResponse({"data": [{"embedding": [0.0]}]})

    monkeypatch.setattr(requests, "post", _requests_post)

    dummy_sync = _DummySyncClient()
    dummy_async = _DummyAsyncClient()

    class _FakePool:
        def get_external_sync_client(self):  # noqa: ANN201
            return dummy_sync

        def get_external_async_client(self):  # noqa: ANN201
            return dummy_async

    monkeypatch.setattr(provider, "get_http_client_pool", lambda: _FakePool(), raising=False)

    model = provider.OpenAICompatibleEmbedding(model="m", base_url="https://example.com/v1/embeddings", api_key="no_api_key")
    vecs = model.encode("hello")

    # After refactor, encode() should use the shared external client, not requests.
    assert spy["requests_post"] == 0
    assert dummy_sync.calls
    _url, headers = dummy_sync.calls[-1]
    assert_no_internal_context_headers(headers)
    assert vecs == [[0.1, 0.2]]


@pytest.mark.asyncio
async def test_openai_embedding_aencode_uses_external_pool_not_new_asyncclient(monkeypatch):
    import app.rag.embedding.providers.openai as provider

    spy = {"asyncclient_ctor": 0}

    class _SpyAsyncClient:  # noqa: D401
        def __init__(self, *args, **kwargs):  # noqa: ANN001
            spy["asyncclient_ctor"] += 1

        async def __aenter__(self):  # noqa: ANN201
            await yield_control()
            return self

        async def __aexit__(self, exc_type, exc, tb):  # noqa: ANN001, ANN201
            await yield_control()
            return False

        async def post(self, *_args, **_kwargs):  # noqa: ANN001, ANN201
            await yield_control()
            return _DummyResponse({"data": [{"embedding": [0.0]}]})

    monkeypatch.setattr(provider.httpx, "AsyncClient", _SpyAsyncClient)

    dummy_sync = _DummySyncClient()
    dummy_async = _DummyAsyncClient()

    class _FakePool:
        def get_external_sync_client(self):  # noqa: ANN201
            return dummy_sync

        def get_external_async_client(self):  # noqa: ANN201
            return dummy_async

    monkeypatch.setattr(provider, "get_http_client_pool", lambda: _FakePool(), raising=False)

    model = provider.OpenAICompatibleEmbedding(model="m", base_url="https://example.com/v1/embeddings", api_key="no_api_key")
    vecs = await model.aencode("hello")

    # After refactor, aencode() should use the shared external client, not a new AsyncClient().
    assert spy["asyncclient_ctor"] == 0
    assert dummy_async.calls
    _url, headers = dummy_async.calls[-1]
    assert_no_internal_context_headers(headers)
    assert vecs == [[0.1, 0.2]]


def test_dashscope_embedding_encode_caps_openai_compatible_batches(monkeypatch):
    import app.rag.embedding.providers.openai as provider

    monkeypatch.setattr(provider.settings, "EMBEDDING_API_BATCH_SIZE", 64, raising=False)

    model = provider.OpenAICompatibleEmbedding(
        model="text-embedding-v3",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings",
        api_key="no_api_key",
    )

    batch_lengths: list[int] = []

    def _capture_batch(texts: list[str]) -> list[list[float]]:
        batch_lengths.append(len(texts))
        return [[0.1, 0.2] for _ in texts]

    monkeypatch.setattr(model, "_encode_one_batch", _capture_batch)

    vecs = model.encode([f"text {idx}" for idx in range(25)])

    assert batch_lengths == [10, 10, 5]
    assert len(vecs) == 25


@pytest.mark.asyncio
async def test_dashscope_embedding_aencode_caps_openai_compatible_batches(monkeypatch):
    import app.rag.embedding.providers.openai as provider

    monkeypatch.setattr(provider.settings, "EMBEDDING_API_BATCH_SIZE", 64, raising=False)

    model = provider.OpenAICompatibleEmbedding(
        model="text-embedding-v3",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings",
        api_key="no_api_key",
    )

    batch_lengths: list[int] = []

    async def _capture_batch(texts: list[str]) -> list[list[float]]:
        batch_lengths.append(len(texts))
        return [[0.1, 0.2] for _ in texts]

    monkeypatch.setattr(model, "_aencode_one_batch", _capture_batch)

    vecs = await model.aencode([f"text {idx}" for idx in range(25)])

    assert batch_lengths == [10, 10, 5]
    assert len(vecs) == 25
