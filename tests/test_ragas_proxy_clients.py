from __future__ import annotations

from collections.abc import Awaitable


class _ClosedAwaitable(Awaitable[None]):
    def __await__(self):  # noqa: ANN204
        if False:
            yield None
        return None


def test_ragas_openai_embeddings_use_proxy_safe_http_clients(monkeypatch) -> None:
    import app.rag.evaluation.ragas as mod

    sync_kwargs = {}
    async_kwargs = {}
    chat_kwargs = {}
    embedding_kwargs = {}

    class _FakeSyncClient:
        def __init__(self, **kwargs):  # noqa: ANN003
            sync_kwargs.update(kwargs)

        def close(self) -> None:
            return None

    class _FakeAsyncClient:
        def __init__(self, **kwargs):  # noqa: ANN003
            async_kwargs.update(kwargs)

        def aclose(self) -> _ClosedAwaitable:
            return _ClosedAwaitable()

    class _FakeChatOpenAI:
        def __init__(self, **kwargs):  # noqa: ANN003
            chat_kwargs.update(kwargs)

    class _FakeOpenAIEmbeddings:
        def __init__(self, **kwargs):  # noqa: ANN003
            embedding_kwargs.update(kwargs)

    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:35983")
    monkeypatch.setenv("ALL_PROXY", "socks://127.0.0.1:35983/")
    monkeypatch.setattr(mod.httpx, "Client", _FakeSyncClient, raising=True)
    monkeypatch.setattr(mod.httpx, "AsyncClient", _FakeAsyncClient, raising=True)
    monkeypatch.setattr(mod, "ChatOpenAI", _FakeChatOpenAI, raising=True)
    monkeypatch.setattr(mod, "OpenAIEmbeddings", _FakeOpenAIEmbeddings, raising=True)
    monkeypatch.setattr(mod.settings, "EMBEDDING_PROVIDER", "openai_compatible", raising=False)

    mod._build_llm_and_embeddings()  # noqa: SLF001

    assert sync_kwargs["trust_env"] is False
    assert async_kwargs["trust_env"] is False
    assert chat_kwargs["http_client"] is not None
    assert chat_kwargs["http_async_client"] is not None
    assert embedding_kwargs["http_client"] is chat_kwargs["http_client"]
    assert embedding_kwargs["http_async_client"] is chat_kwargs["http_async_client"]
