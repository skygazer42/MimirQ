from __future__ import annotations

import json


class _DummyEmbeddingModel:
    def __init__(self) -> None:
        self.dimension = 2
        self.calls: list[list[str]] = []

    def encode(self, message):  # noqa: ANN001, ANN201
        if isinstance(message, str):
            texts = [message]
        else:
            texts = list(message or [])
        self.calls.append(texts)
        return [[float(len(t)), 0.0] for t in texts]


class _FakePipeline:
    def __init__(self, redis):  # noqa: ANN001
        self._redis = redis
        self._sets: list[tuple[str, bytes]] = []

    def set(self, key, payload, ex=None):  # noqa: ANN001, ANN201
        self._sets.append((str(key), bytes(payload)))
        return True

    def execute(self):  # noqa: ANN201
        for k, v in self._sets:
            self._redis._store[k] = v
        return True


class _FakeRedis:
    def __init__(self, store: dict[str, bytes] | None = None) -> None:
        self._store = dict(store or {})

    def mget(self, keys):  # noqa: ANN001, ANN201
        return [self._store.get(str(k)) for k in (keys or [])]

    def pipeline(self, transaction=False):  # noqa: ANN001, ANN201
        return _FakePipeline(self)

    def get(self, key):  # noqa: ANN001, ANN201
        return self._store.get(str(key))

    def set(self, key, payload, ex=None):  # noqa: ANN001, ANN201
        self._store[str(key)] = bytes(payload)
        return True


def test_embedding_cache_metrics_documents(monkeypatch):  # noqa: ANN001
    import app.rag.embedding.adapter as adapter_mod
    from app.core.config import settings

    monkeypatch.setattr(settings, "EMBEDDING_CACHE_ENABLED", True, raising=False)

    metrics: list[dict] = []
    monkeypatch.setattr(adapter_mod, "log_metrics", lambda payload: metrics.append(dict(payload)), raising=True)
    monkeypatch.setattr(adapter_mod, "_embed_cache_key", lambda t: f"k:{t}", raising=True)

    store = {
        "k:a": json.dumps([1.0, 2.0]).encode("utf-8"),
    }
    fake = _FakeRedis(store)
    monkeypatch.setattr(adapter_mod, "_get_redis_client", lambda: fake, raising=True)

    model = _DummyEmbeddingModel()
    adapter = adapter_mod.LangChainEmbeddingsAdapter(model, normalize=False)

    out = adapter.embed_documents(["a", "bb"])
    assert out == [[1.0, 2.0], [2.0, 0.0]]
    assert model.calls == [["bb"]]

    doc_events = [m for m in metrics if m.get("event") == "embedding.cache" and m.get("op") == "documents"]
    assert doc_events, "Expected embedding.cache documents event"
    last = doc_events[-1]
    assert last.get("total") == 2
    assert last.get("hits") == 1
    assert last.get("misses") == 1
    assert last.get("corrupt") == 0


def test_embedding_cache_metrics_query(monkeypatch):  # noqa: ANN001
    import app.rag.embedding.adapter as adapter_mod
    from app.core.config import settings

    monkeypatch.setattr(settings, "EMBEDDING_CACHE_ENABLED", True, raising=False)

    metrics: list[dict] = []
    monkeypatch.setattr(adapter_mod, "log_metrics", lambda payload: metrics.append(dict(payload)), raising=True)
    monkeypatch.setattr(adapter_mod, "_embed_cache_key", lambda t: f"k:{t}", raising=True)

    store = {
        "k:q": json.dumps([3.0, 4.0]).encode("utf-8"),
    }
    fake = _FakeRedis(store)
    monkeypatch.setattr(adapter_mod, "_get_redis_client", lambda: fake, raising=True)

    model = _DummyEmbeddingModel()
    adapter = adapter_mod.LangChainEmbeddingsAdapter(model, normalize=False)

    out = adapter.embed_query("q")
    assert out == [3.0, 4.0]
    assert model.calls == []

    query_events = [m for m in metrics if m.get("event") == "embedding.cache" and m.get("op") == "query"]
    assert query_events, "Expected embedding.cache query event"
    last = query_events[-1]
    assert last.get("total") == 1
    assert last.get("hits") == 1
    assert last.get("misses") == 0

