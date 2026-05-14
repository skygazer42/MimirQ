from __future__ import annotations

from app.services.dataset_embedding_config import resolve_dataset_embedding_runtime


def test_dataset_embedding_runtime_uses_separate_collection_for_dataset_override(monkeypatch):  # noqa: ANN001
    import app.services.dataset_embedding_config as runtime_mod

    monkeypatch.setattr(runtime_mod.settings, "EMBEDDING_PROVIDER", "openai_compatible", raising=False)
    monkeypatch.setattr(runtime_mod.settings, "EMBEDDING_MODEL", "text-embedding-3-small", raising=False)
    monkeypatch.setattr(runtime_mod.settings, "EMBEDDING_API_BASE", "https://global.example/v1", raising=False)
    monkeypatch.setattr(runtime_mod.settings, "MILVUS_COLLECTION_NAME", "documents", raising=False)

    runtime = resolve_dataset_embedding_runtime(
        {
            "embedding_defaults": {
                "provider": "openai_compatible",
                "model": "bge-large-zh",
                "api_base": "https://dataset.example/v1",
            }
        }
    )

    assert runtime.dataset_scoped is True
    assert runtime.model == "bge-large-zh"
    assert runtime.api_base == "https://dataset.example/v1"
    assert runtime.collection_name.startswith("documents_emb_")
    assert runtime.embedding_space_hash in runtime.collection_name


def test_indexer_and_retriever_route_dataset_scoped_embeddings_to_runtime_collections() -> None:
    indexer_src = open("app/services/indexer.py", encoding="utf-8").read()
    retriever_src = open("app/rag/retriever.py", encoding="utf-8").read()

    assert "resolve_dataset_embedding_runtime(dataset_meta)" in indexer_src
    assert "meta.setdefault(\"embedding_space_hash\", embedding_space)" in indexer_src
    assert "create_embeddings_for_runtime(runtime)" in indexer_src
    assert "get_milvus_adapter(resolve_collection_name(runtime.collection_name))" in indexer_src
    assert "adapter.add_vectors(items, embeddings=vectors" in indexer_src

    assert "def _search_dataset_scoped_vectors(" in retriever_src
    assert "create_embeddings_for_runtime(embedding_runtime)" in retriever_src
    assert "embeddings.embed_query(query)" in retriever_src
    assert "resolve_collection_name(embedding_runtime.collection_name)" in retriever_src
    assert "if embedding_runtime.dataset_scoped:" in retriever_src
    assert "semantic_cache_eligible = False" in retriever_src
