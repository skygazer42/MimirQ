from __future__ import annotations

from uuid import uuid4

import pytest

from app.core.config import Settings
from app.rag.embedding.utils import embedding_space_hash_for_config


def test_embedding_space_hash_for_config_normalizes_base_url() -> None:
    h1 = embedding_space_hash_for_config(
        provider="openai_compatible",
        model="text-embedding-x",
        base_url="https://api.example.com/v1?foo=bar#frag",
        length=16,
    )
    h2 = embedding_space_hash_for_config(
        provider="openai_compatible",
        model="text-embedding-x",
        base_url="https://api.example.com/v1",
        length=16,
    )
    assert h1 == h2


def test_shadow_settings_validation_requires_model_and_collection() -> None:
    with pytest.raises(ValueError):
        Settings(
            VECTOR_BACKEND="milvus",
            EMBEDDING_SHADOW_ENABLED=True,
            EMBEDDING_SHADOW_MODEL="",
            MILVUS_SHADOW_COLLECTION_NAME="documents_shadow",
        )

    with pytest.raises(ValueError):
        Settings(
            VECTOR_BACKEND="milvus",
            EMBEDDING_SHADOW_ENABLED=True,
            EMBEDDING_SHADOW_MODEL="text-embedding-new",
            MILVUS_SHADOW_COLLECTION_NAME="",
        )

    with pytest.raises(ValueError):
        Settings(
            VECTOR_BACKEND="milvus",
            EMBEDDING_SHADOW_ENABLED=True,
            EMBEDDING_SHADOW_MODEL="text-embedding-new",
            MILVUS_COLLECTION_NAME="documents",
            MILVUS_SHADOW_COLLECTION_NAME="documents",
        )


def test_dual_write_shadow_vectors_best_effort_writes_shadow_vectors(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services.indexer as indexer_mod

    # Reset cached writer state.
    indexer_mod._shadow_vector_writer_sig = None
    indexer_mod._shadow_vector_writer = None

    # Configure shadow dual-write.
    monkeypatch.setattr(indexer_mod.settings, "VECTOR_BACKEND", "milvus", raising=False)
    monkeypatch.setattr(indexer_mod.settings, "MILVUS_COLLECTION_NAME", "documents", raising=False)
    monkeypatch.setattr(indexer_mod.settings, "MILVUS_SHADOW_COLLECTION_NAME", "documents_shadow", raising=False)
    monkeypatch.setattr(indexer_mod.settings, "EMBEDDING_SHADOW_ENABLED", True, raising=False)
    monkeypatch.setattr(indexer_mod.settings, "EMBEDDING_SHADOW_PROVIDER", "openai_compatible", raising=False)
    monkeypatch.setattr(indexer_mod.settings, "EMBEDDING_SHADOW_MODEL", "text-embedding-new", raising=False)
    monkeypatch.setattr(indexer_mod.settings, "EMBEDDING_SHADOW_API_BASE", "https://api.example.com/v1", raising=False)
    monkeypatch.setattr(indexer_mod.settings, "EMBEDDING_SHADOW_API_KEY", "sk-test", raising=False)
    monkeypatch.setattr(indexer_mod.settings, "VECTOR_WRITE_BATCH_SIZE", 10, raising=False)

    calls: dict[str, object] = {}

    class FakeEmbeddings:
        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            # Return a deterministic vector per text (dim=3).
            return [[float(len(t)), 0.0, 1.0] for t in texts]

    class FakeAdapter:
        def add_vectors(self, items, embeddings=None, batch_size=1000, timeout=None, upsert=True, **kwargs):  # noqa: ANN001
            calls["items"] = items
            calls["embeddings"] = embeddings
            calls["batch_size"] = batch_size
            calls["upsert"] = upsert
            return [str(it.get("id")) for it in items]

    monkeypatch.setattr(indexer_mod, "create_langchain_embeddings_from_config", lambda **_k: FakeEmbeddings())
    monkeypatch.setattr(indexer_mod, "get_milvus_adapter", lambda _name: FakeAdapter())
    monkeypatch.setattr(indexer_mod, "resolve_collection_name", lambda name: name)
    monkeypatch.setattr(indexer_mod, "log_metrics", lambda _payload: None)

    document_id = uuid4()
    tenant_id = uuid4()

    docs = [
        {"content": "hello", "metadata": {"chunk_id": "cid1", "embedding_space_hash": "old"}},
        {"content": "world", "metadata": {"chunk_id": "cid2", "embedding_space_hash": "old"}},
    ]

    indexer_mod._dual_write_shadow_vectors_best_effort(docs, document_id=document_id, tenant_id=tenant_id)

    assert calls.get("upsert") is True
    items = calls.get("items")
    assert isinstance(items, list)
    assert {it.get("id") for it in items} == {"cid1", "cid2"}

    expected_space = embedding_space_hash_for_config(
        provider="openai_compatible",
        model="text-embedding-new",
        base_url="https://api.example.com/v1",
        length=16,
    )
    for it in items:
        meta = it.get("metadata") or {}
        assert meta.get("embedding_space_hash") == expected_space

