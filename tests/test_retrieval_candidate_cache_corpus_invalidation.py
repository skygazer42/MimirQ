from __future__ import annotations

from uuid import uuid4

import pytest

from app.core.config import settings
from app.rag.retriever import HybridRetriever


class _StubVectorStore:
    def __init__(self, *, dataset_id: str) -> None:
        self.calls = 0
        self._dataset_id = dataset_id

    def search(self, **_kwargs):  # noqa: ANN003
        self.calls += 1
        return [
            {
                "chunk_id": "chunk-1",
                "content": "vector hit",
                "metadata": {
                    "document_id": "doc-1",
                    "dataset_id": self._dataset_id,
                    "chunk_index": 0,
                    "chunk_id": "chunk-1",
                },
                "score": 0.91,
            }
        ]


def test_candidate_cache_hits_same_token_and_misses_after_corpus_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.retriever as retriever_mod

    tenant_id = uuid4()
    dataset_id = uuid4()
    retriever = HybridRetriever(tenant_id=tenant_id, dataset_id=dataset_id, account_id="acct-1")

    monkeypatch.setattr(settings, "RETRIEVAL_CANDIDATE_CACHE_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_CANDIDATE_CACHE_TTL_SEC", 60, raising=False)
    monkeypatch.setattr(settings, "LEXICAL_DB_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "BM25_INDEX_ENABLED", False, raising=False)

    stub_store = _StubVectorStore(dataset_id=str(dataset_id))
    monkeypatch.setattr(retriever_mod, "get_vector_store", lambda: stub_store, raising=True)
    monkeypatch.setattr(retriever, "_search_bm25", lambda **_k: [], raising=False)
    monkeypatch.setattr(retriever, "_search_lexical_db", lambda **_k: [], raising=False)
    monkeypatch.setattr(retriever, "_enrich_results_with_db_metadata", lambda r, **_k: r, raising=False)
    monkeypatch.setattr(retriever, "_expand_results_with_neighbors", lambda r: r, raising=False)
    monkeypatch.setattr(retriever, "_auto_merge_parent_child", lambda r: r, raising=False)

    cache_store: dict[str, list[dict]] = {}
    monkeypatch.setattr(retriever_mod, "get_cached_retrieval_candidates", lambda key: cache_store.get(key), raising=True)
    monkeypatch.setattr(
        retriever_mod,
        "set_cached_retrieval_candidates",
        lambda key, payload: cache_store.setdefault(key, list(payload)) is not None,
        raising=True,
    )
    monkeypatch.setattr(retriever_mod, "current_embedding_space_hash", lambda: "embspace-a", raising=True)

    token_box = {"value": "corp-a"}
    monkeypatch.setattr(
        retriever,
        "_resolve_candidate_cache_corpus_token",
        lambda **_k: token_box["value"],
        raising=False,
    )

    out1 = retriever._hybrid_search("hello", top_k=1, retrieval_mode="vector", score_threshold=0.0)
    assert len(out1) == 1
    assert stub_store.calls == 1

    out2 = retriever._hybrid_search("hello", top_k=1, retrieval_mode="vector", score_threshold=0.0)
    assert len(out2) == 1
    assert stub_store.calls == 1
    cache_meta_hit = retriever._last_channel_metrics.get("cache") or {}
    assert cache_meta_hit.get("enabled") is True
    assert cache_meta_hit.get("hit") is True

    token_box["value"] = "corp-b"
    out3 = retriever._hybrid_search("hello", top_k=1, retrieval_mode="vector", score_threshold=0.0)
    assert len(out3) == 1
    assert stub_store.calls == 2

    cache_meta_miss = retriever._last_channel_metrics.get("cache") or {}
    assert cache_meta_miss.get("enabled") is True
    assert cache_meta_miss.get("hit") is False
    assert cache_meta_miss.get("store_ok") is True
    assert len(cache_store) == 2


def test_candidate_cache_skips_when_corpus_token_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.retriever as retriever_mod

    tenant_id = uuid4()
    dataset_id = uuid4()
    retriever = HybridRetriever(tenant_id=tenant_id, dataset_id=dataset_id, account_id="acct-1")

    monkeypatch.setattr(settings, "RETRIEVAL_CANDIDATE_CACHE_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_CANDIDATE_CACHE_TTL_SEC", 60, raising=False)
    monkeypatch.setattr(settings, "LEXICAL_DB_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "BM25_INDEX_ENABLED", False, raising=False)

    stub_store = _StubVectorStore(dataset_id=str(dataset_id))
    monkeypatch.setattr(retriever_mod, "get_vector_store", lambda: stub_store, raising=True)
    monkeypatch.setattr(retriever, "_search_bm25", lambda **_k: [], raising=False)
    monkeypatch.setattr(retriever, "_search_lexical_db", lambda **_k: [], raising=False)
    monkeypatch.setattr(retriever, "_enrich_results_with_db_metadata", lambda r, **_k: r, raising=False)
    monkeypatch.setattr(retriever, "_expand_results_with_neighbors", lambda r: r, raising=False)
    monkeypatch.setattr(retriever, "_auto_merge_parent_child", lambda r: r, raising=False)
    monkeypatch.setattr(retriever_mod, "current_embedding_space_hash", lambda: "embspace-a", raising=True)
    monkeypatch.setattr(retriever, "_resolve_candidate_cache_corpus_token", lambda **_k: None, raising=False)

    get_calls = {"count": 0}
    set_calls = {"count": 0}
    monkeypatch.setattr(
        retriever_mod,
        "get_cached_retrieval_candidates",
        lambda _key: get_calls.__setitem__("count", get_calls["count"] + 1) or None,
        raising=True,
    )
    monkeypatch.setattr(
        retriever_mod,
        "set_cached_retrieval_candidates",
        lambda _key, _payload: set_calls.__setitem__("count", set_calls["count"] + 1) or True,
        raising=True,
    )

    out = retriever._hybrid_search("hello", top_k=1, retrieval_mode="vector", score_threshold=0.0)

    assert len(out) == 1
    assert stub_store.calls == 1
    assert get_calls["count"] == 0
    assert set_calls["count"] == 0

    cache_meta = retriever._last_channel_metrics.get("cache") or {}
    assert cache_meta.get("enabled") is True
    assert cache_meta.get("hit") is False
    assert cache_meta.get("skip_reason") == "missing_corpus_cache_token"
