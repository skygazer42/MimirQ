from __future__ import annotations

from app.rag.embedding.adapter import LangChainEmbeddingsAdapter
from app.rag.embedding.base import BaseEmbeddingModel
from tests.helpers.async_utils import yield_control


class _DummyEmbeddingModel(BaseEmbeddingModel):
    def __init__(self) -> None:
        super().__init__(model="dummy", dimension=1)

    def encode(self, message):  # noqa: ANN001
        texts = [message] if isinstance(message, str) else list(message)
        return [[float(len(t))] for t in texts]

    async def aencode(self, message):  # noqa: ANN001
        await yield_control()
        return self.encode(message)


def test_embed_documents_cache_failure_falls_back(monkeypatch):
    import app.rag.embedding.adapter as adapter_mod

    class _BrokenRedis:
        def mget(self, _keys):  # noqa: ANN001
            raise RuntimeError("redis down")

    monkeypatch.setattr(adapter_mod, "_get_redis_client", lambda: _BrokenRedis())
    monkeypatch.setattr(adapter_mod.settings, "EMBEDDING_CACHE_ENABLED", True, raising=False)

    adapter = LangChainEmbeddingsAdapter(_DummyEmbeddingModel(), normalize=False)
    vecs = adapter.embed_documents(["a", "bbbb"])

    assert vecs == [[1.0], [4.0]]


def test_embed_query_cache_failure_falls_back(monkeypatch):
    import app.rag.embedding.adapter as adapter_mod

    class _BrokenRedis:
        def get(self, _key):  # noqa: ANN001
            raise RuntimeError("redis down")

        def set(self, *_args, **_kwargs):  # noqa: ANN001
            raise RuntimeError("redis down")

    monkeypatch.setattr(adapter_mod, "_get_redis_client", lambda: _BrokenRedis())
    monkeypatch.setattr(adapter_mod.settings, "EMBEDDING_CACHE_ENABLED", True, raising=False)

    adapter = LangChainEmbeddingsAdapter(_DummyEmbeddingModel(), normalize=False)
    vec = adapter.embed_query("hello")

    assert vec == [5.0]
