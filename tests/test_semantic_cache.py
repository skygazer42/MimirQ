from __future__ import annotations

import json

import pytest

from app.core.config import settings
from app.services import semantic_cache as sc


def test_build_semantic_cache_scope_hash_and_vector_id_do_not_leak_query() -> None:
    scope_hash, vector_id = sc.build_semantic_cache_scope_hash(
        tenant_id="t1",
        account_id="a1",
        dataset_id="d1",
        corpus_cache_token="tok",
        query="super secret query",
        top_k=5,
        score_threshold=0.0,
        retrieval_mode="hybrid",
        metadata_filter={"file_type": {"$eq": "pdf"}},
        document_ids=["doc1", "doc2"],
    )
    assert scope_hash and vector_id
    assert "super secret query" not in scope_hash
    assert "super secret query" not in vector_id
    assert scope_hash != vector_id


def test_get_cached_semantic_payload_hits_when_scope_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "SEMANTIC_CACHE_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "SEMANTIC_CACHE_TTL_SEC", 300, raising=False)
    monkeypatch.setattr(settings, "SEMANTIC_CACHE_SCORE_THRESHOLD", 0.95, raising=False)
    monkeypatch.setattr(settings, "SEMANTIC_CACHE_SEARCH_TOP_K", 5, raising=False)
    monkeypatch.setattr(settings, "SEMANTIC_CACHE_REDIS_PREFIX", "semc", raising=False)

    monkeypatch.setattr(sc, "current_embedding_space_hash", lambda: "space")

    scope_hash, vector_id = sc.build_semantic_cache_scope_hash(
        tenant_id="t1",
        account_id="a1",
        dataset_id="d1",
        corpus_cache_token="tok",
        query="hello world",
        top_k=5,
        score_threshold=0.0,
        retrieval_mode="hybrid",
        metadata_filter=None,
        document_ids=["doc1"],
    )

    payload = [{"chunk_id": "c1", "score": 1.0, "content": "x", "metadata": {}}]
    redis_key = f"semc:t1:{vector_id}"

    class _FakeRedis:
        def get(self, key):  # noqa: ANN001
            return json.dumps(payload).encode("utf-8") if key == redis_key else None

    class _FakeEmb:
        def embed_query(self, _q):  # noqa: ANN001
            return [0.1, 0.2, 0.3]

    class _FakeAdapter:
        def search(self, _vec, top_k, metadata_filter=None):  # noqa: ANN001
            assert top_k >= 1
            assert metadata_filter == {"tenant_id": "t1"}
            return [
                {
                    "id": vector_id,
                    "score": 0.97,
                    "content": "",
                    "metadata": {
                        "tenant_id": "t1",
                        "account_id": "a1",
                        "scope_hash": scope_hash,
                        "corpus_cache_token": "tok",
                        "embedding_space_hash": "space",
                    },
                }
            ]

        def delete(self, _ids):  # noqa: ANN001
            raise AssertionError("delete should not be called on hit")

    monkeypatch.setattr(sc, "_get_redis_client", lambda: _FakeRedis())
    monkeypatch.setattr(sc, "_get_embeddings", lambda: _FakeEmb())
    monkeypatch.setattr(sc, "_get_adapter", lambda: _FakeAdapter())

    out, meta = sc.get_cached_semantic_payload(
        tenant_id="t1",
        account_id="a1",
        dataset_id="d1",
        corpus_cache_token="tok",
        query="hello world",
        top_k=5,
        score_threshold=0.0,
        retrieval_mode="hybrid",
        metadata_filter=None,
        document_ids=["doc1"],
    )
    assert out == payload
    assert meta.get("hit") is True
    assert meta.get("vector_id") == vector_id

