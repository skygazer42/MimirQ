import asyncio
import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import replace
from types import SimpleNamespace

import pytest


def _embedding_runtime():
    from app.services.dataset_embedding_config import DatasetEmbeddingRuntimeConfig

    return DatasetEmbeddingRuntimeConfig(
        provider="local",
        model="test-model",
        api_base="",
        api_key="",
        embedding_space_hash="test-space",
        collection_name="documents_test_space",
        dataset_scoped=False,
    )


def test_default_vector_write_failure_raises_and_recovery_can_succeed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.indexer import Indexer

    attempts = 0

    def fail_write(self, docs, *, document_id, tenant_id):  # noqa: ANN001,ARG001
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("vector backend unavailable")
        return ["vector-1"]

    monkeypatch.setattr(Indexer, "_write_default_chunk_vectors", fail_write)
    indexer = Indexer.__new__(Indexer)

    with pytest.raises(RuntimeError, match="vector backend unavailable"):
        indexer._index_chunk_vectors(
            [{"content": "chunk"}],
            document_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            enable_vectors=True,
            embedding_runtime=_embedding_runtime(),
        )

    assert indexer._index_chunk_vectors(
        [{"content": "chunk"}],
        document_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        enable_vectors=True,
        embedding_runtime=_embedding_runtime(),
    ) == ["vector-1"]


def test_dataset_scoped_vector_write_retries_without_reembedding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.indexer as indexer_module

    class _Embeddings:
        calls = 0

        def embed_documents(self, texts):  # noqa: ANN001
            self.calls += 1
            return [[1.0] for _ in texts]

    class _Adapter:
        calls = 0

        def add_vectors(self, items, **_kwargs):  # noqa: ANN001
            self.calls += 1
            if self.calls == 1:
                raise ConnectionError("transient")
            return [str(item["id"]) for item in items]

    embeddings = _Embeddings()
    adapter = _Adapter()
    monkeypatch.setattr(indexer_module, "create_embeddings_for_runtime", lambda _runtime: embeddings)
    monkeypatch.setattr(indexer_module, "get_milvus_adapter", lambda _name: adapter)
    monkeypatch.setattr(indexer_module, "_vector_write_retry_policy", lambda: (1, 0.0))
    monkeypatch.setattr(indexer_module.time, "sleep", lambda _seconds: None)

    document_id = uuid.uuid4()
    result = indexer_module.Indexer.__new__(indexer_module.Indexer)._write_dataset_scoped_chunk_vectors(
        [{"content": "chunk", "metadata": {"chunk_id": "chunk-1"}}],
        document_id=document_id,
        tenant_id=uuid.uuid4(),
        runtime=replace(_embedding_runtime(), dataset_scoped=True),
    )

    assert result == ["chunk-1"]
    assert embeddings.calls == 1
    assert adapter.calls == 2


def test_dataset_scoped_vector_write_rejects_misaligned_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.indexer as indexer_module

    embeddings = SimpleNamespace(embed_documents=lambda texts: [[1.0] for _ in texts])
    adapter = SimpleNamespace(add_vectors=lambda *_args, **_kwargs: [])
    monkeypatch.setattr(indexer_module, "create_embeddings_for_runtime", lambda _runtime: embeddings)
    monkeypatch.setattr(indexer_module, "get_milvus_adapter", lambda _name: adapter)

    with pytest.raises(ValueError, match="vector ids length 0 != docs length 1"):
        indexer_module.Indexer.__new__(indexer_module.Indexer)._write_dataset_scoped_chunk_vectors(
            [{"content": "chunk", "metadata": {"chunk_id": "chunk-1"}}],
            document_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            runtime=replace(_embedding_runtime(), dataset_scoped=True),
        )


def test_milvus_write_fallback_keeps_required_routing_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.storage.vector.milvus import MilvusVectorStore

    calls: list[list[dict[str, object]]] = []

    class _Store:
        def add_texts(self, *, texts, metadatas, ids):  # noqa: ANN001, ANN202
            calls.append([dict(metadata) for metadata in metadatas])
            if len(calls) == 1:
                raise RuntimeError("legacy collection rejects indexed metadata slots")
            return ids

    vector_store = object.__new__(MilvusVectorStore)
    vector_store._store = _Store()
    monkeypatch.setattr(vector_store, "_require_store", lambda: vector_store._store)

    dataset_id = uuid.uuid4()
    result = vector_store.add_documents(
        [
            {
                "content": "chunk",
                "metadata": {
                    "chunk_id": "chunk-1",
                    "dataset_id": str(dataset_id),
                    "embedding_space_hash": "space-a",
                    "_indexed_metadata": {"region": "east"},
                },
            }
        ],
        document_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
    )

    assert result == ["chunk-1"]
    assert len(calls) == 2
    assert calls[1][0]["dataset_id"] == str(dataset_id)
    assert calls[1][0]["embedding_space_hash"] == "space-a"
    assert not any(key.startswith("indexed_meta_") for key in calls[1][0])


def test_indexer_embedding_runtime_for_document_propagates_invalid_dataset_scoped_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.indexer as indexer_module

    tenant_id = uuid.uuid4()
    document_id = uuid.uuid4()

    class _Query:
        def filter(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            return self

        def first(self):  # noqa: ANN202
            return (uuid.uuid4(),)

    indexer = indexer_module.Indexer.__new__(indexer_module.Indexer)
    indexer._db = SimpleNamespace(query=lambda *_args, **_kwargs: _Query())
    monkeypatch.setattr(indexer_module.settings, "VECTOR_BACKEND", "faiss", raising=False)
    monkeypatch.setattr(
        indexer,
        "_load_dataset_metadata",
        lambda **_kwargs: {"embedding_defaults": {"provider": "local", "model": "embed-a"}},
        raising=False,
    )

    with pytest.raises(ValueError, match="VECTOR_BACKEND=milvus"):
        indexer._embedding_runtime_for_document(tenant_id=tenant_id, document_id=document_id)


def _configure_retrieval_test(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings

    for name, value in {
        "BM25_INDEX_ENABLED": True,
        "COLBERT_RETRIEVAL_ENABLED": False,
        "COLPALI_RETRIEVAL_ENABLED": False,
        "LEXICAL_DB_ENABLED": False,
        "RETRIEVAL_CANDIDATE_CACHE_ENABLED": False,
        "SEMANTIC_CACHE_ENABLED": False,
        "RAG_CONTEXT_STITCHING_ENABLED": False,
        "RETRIEVAL_GOVERNANCE_PREFER_AUTHORITY": False,
        "RETRIEVAL_GOVERNANCE_PREFER_LATEST": False,
        "RETRIEVAL_GOVERNANCE_FILTER_SUPERSEDED": False,
    }.items():
        monkeypatch.setattr(settings, name, value, raising=False)


def _retriever(monkeypatch: pytest.MonkeyPatch):
    import app.rag.retriever as retriever_module
    from app.rag.retriever import HybridRetriever

    _configure_retrieval_test(monkeypatch)
    runtime = _embedding_runtime()
    monkeypatch.setattr(HybridRetriever, "_resolve_embedding_runtime", lambda self, *, tenant_id: runtime)
    monkeypatch.setattr(
        HybridRetriever,
        "_resolve_document_dataset_scope",
        lambda self, *, tenant_id, document_ids: ((), True),  # noqa: ANN001,ARG005
    )
    monkeypatch.setattr(
        HybridRetriever,
        "_enrich_results_with_db_metadata",
        lambda self, results, **kwargs: list(results),
    )
    monkeypatch.setattr(HybridRetriever, "_expand_results_with_neighbors", lambda self, results: list(results))
    monkeypatch.setattr(HybridRetriever, "_auto_merge_parent_child", lambda self, results: list(results))
    vector_store = SimpleNamespace(search=lambda **kwargs: [])
    monkeypatch.setattr(retriever_module, "get_vector_store", lambda: vector_store)
    retriever = HybridRetriever(
        k=1,
        document_ids=[uuid.uuid4()],
        retrieval_mode="hybrid",
        sparse_enabled=False,
        enable_reranker=False,
        dedup_enabled=False,
        max_chunks_per_doc=0,
        max_chunks_per_page=0,
        min_distinct_docs=0,
    )
    return retriever, vector_store


def test_multi_dataset_scope_is_a_first_class_retrieval_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import settings
    from app.rag.retriever import HybridRetriever

    _configure_retrieval_test(monkeypatch)
    monkeypatch.setattr(settings, "CHAT_ALLOW_OPEN_SCOPE", False, raising=False)
    monkeypatch.setattr(
        HybridRetriever,
        "_resolve_embedding_runtime",
        lambda self, *, tenant_id: _embedding_runtime(),
    )
    monkeypatch.setattr(
        HybridRetriever,
        "_enrich_results_with_db_metadata",
        lambda self, results, **kwargs: list(results),
    )
    monkeypatch.setattr(HybridRetriever, "_expand_results_with_neighbors", lambda self, results: list(results))
    monkeypatch.setattr(HybridRetriever, "_auto_merge_parent_child", lambda self, results: list(results))

    tenant_id = uuid.uuid4()
    dataset_a = uuid.uuid4()
    dataset_b = uuid.uuid4()
    captured: dict[str, object] = {}

    def hybrid_search(self, query, **kwargs):  # noqa: ANN001,ARG001
        captured["metadata_filter"] = kwargs.get("metadata_filter")
        return [
            {
                "chunk_id": str(uuid.uuid4()),
                "content": "scoped result",
                "score": 0.9,
                "metadata": {"dataset_id": str(dataset_a)},
            }
        ]

    monkeypatch.setattr(HybridRetriever, "_hybrid_search", hybrid_search)
    retriever = HybridRetriever(
        tenant_id=tenant_id,
        dataset_ids=[dataset_b, dataset_a, dataset_b],
        k=1,
        enable_reranker=False,
    )

    docs = retriever.invoke("scope query")

    assert [doc.page_content for doc in docs] == ["scoped result"]
    assert captured["metadata_filter"] == {
        "dataset_id": {"$in": [str(dataset_id) for dataset_id in sorted((dataset_a, dataset_b), key=str)]}
    }
    assert retriever._last_debug_metrics["scope"]["kind"] == "dataset_ids"
    assert retriever._last_debug_metrics["scope"]["dataset_ids_count"] == 2


def test_retriever_embedding_runtime_propagates_invalid_dataset_scoped_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.retriever as retriever_module
    from app.rag.retriever import HybridRetriever

    _configure_retrieval_test(monkeypatch)
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()

    class _Query:
        def filter(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            return self

        def first(self):  # noqa: ANN202
            return ({"embedding_defaults": {"provider": "local", "model": "embed-a"}},)

        def all(self):  # noqa: ANN202
            return [(dataset_id, {"embedding_defaults": {"provider": "local", "model": "embed-a"}})]

    class _Session:
        def query(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            return _Query()

        def close(self) -> None:
            return None

    monkeypatch.setattr(retriever_module.settings, "VECTOR_BACKEND", "faiss", raising=False)
    monkeypatch.setattr(retriever_module, "SessionLocal", lambda: _Session(), raising=True)

    with pytest.raises(ValueError, match="VECTOR_BACKEND=milvus"):
        HybridRetriever(tenant_id=tenant_id, dataset_ids=[dataset_id])._resolve_embedding_runtime(
            tenant_id=tenant_id
        )


@pytest.mark.parametrize("retrieval_mode", ["vector", "keyword"])
@pytest.mark.parametrize("scope_kind", ["dataset_ids", "document_ids"])
def test_multi_runtime_dataset_scope_fans_out_vector_search_and_keeps_exact_cache_enabled(
    monkeypatch: pytest.MonkeyPatch,
    retrieval_mode: str,
    scope_kind: str,
) -> None:
    import app.rag.retriever as retriever_module
    from app.core.config import settings
    from app.rag.retriever import HybridRetriever
    from app.services.dataset_embedding_config import DatasetEmbeddingRuntimeConfig

    _configure_retrieval_test(monkeypatch)
    for name, value in {
        "RETRIEVAL_CANDIDATE_CACHE_ENABLED": True,
        "RETRIEVAL_CANDIDATE_CACHE_TTL_SEC": 60,
        "SEMANTIC_CACHE_ENABLED": True,
        "SEMANTIC_CACHE_TTL_SEC": 60,
    }.items():
        monkeypatch.setattr(settings, name, value, raising=False)

    tenant_id = uuid.uuid4()
    dataset_a = uuid.uuid4()
    dataset_b = uuid.uuid4()
    document_a = uuid.uuid4()
    document_b = uuid.uuid4()
    runtime_a = DatasetEmbeddingRuntimeConfig(
        provider="local",
        model="model-a",
        api_base="",
        api_key="",
        embedding_space_hash="space-a",
        collection_name="documents_emb_space_a",
        dataset_scoped=True,
    )
    runtime_b = DatasetEmbeddingRuntimeConfig(
        provider="local",
        model="model-b",
        api_base="",
        api_key="",
        embedding_space_hash="space-b",
        collection_name="documents_emb_space_b",
        dataset_scoped=True,
    )
    search_calls: list[dict[str, object]] = []
    cache_lookups: list[str] = []
    cache_key_calls: list[dict[str, object]] = []

    class _Embeddings:
        def __init__(self, runtime: DatasetEmbeddingRuntimeConfig) -> None:
            self.runtime = runtime

        def embed_query(self, _query: str) -> list[float]:
            return [1.0 if self.runtime.embedding_space_hash == "space-a" else 2.0]

    class _Adapter:
        def __init__(self, runtime: DatasetEmbeddingRuntimeConfig) -> None:
            self.runtime = runtime

        def search(self, *, query_vector, top_k, metadata_filter):  # noqa: ANN001
            search_calls.append(
                {
                    "collection": self.runtime.collection_name,
                    "query_vector": list(query_vector),
                    "top_k": top_k,
                    "metadata_filter": metadata_filter,
                }
            )
            if self.runtime is runtime_b:
                raise RuntimeError("secondary shard unavailable")
            return [
                {
                    "id": "chunk-a",
                    "content": "runtime a hit",
                    "score": 0.91,
                    "metadata": {
                        "chunk_id": "chunk-a",
                        "document_id": str(document_a),
                        "dataset_id": str(dataset_a),
                        "embedding_space_hash": runtime_a.embedding_space_hash,
                    },
                }
            ]

    monkeypatch.setattr(
        HybridRetriever,
        "_resolve_dataset_runtime_shards",
        lambda self, *, tenant_id, dataset_ids=None: [  # noqa: ANN001,ARG005
            (runtime_a, (dataset_a,)),
            (runtime_b, (dataset_b,)),
        ],
    )
    monkeypatch.setattr(
        HybridRetriever,
        "_resolve_document_dataset_scope",
        lambda self, *, tenant_id, document_ids: ((dataset_a, dataset_b), False),  # noqa: ANN001,ARG005
        raising=False,
    )
    monkeypatch.setattr(
        HybridRetriever,
        "_resolve_embedding_runtime",
        lambda self, *, tenant_id: _embedding_runtime(),  # noqa: ANN001,ARG005
    )
    monkeypatch.setattr(
        HybridRetriever,
        "_resolve_candidate_cache_corpus_token",
        lambda self, **kwargs: "corpus-token",  # noqa: ANN001,ARG005
    )
    monkeypatch.setattr(retriever_module, "create_embeddings_for_runtime", lambda runtime: _Embeddings(runtime))
    monkeypatch.setattr(retriever_module, "resolve_collection_name", lambda name: name)
    monkeypatch.setattr(
        retriever_module,
        "get_milvus_adapter",
        lambda name: _Adapter(runtime_a if name == runtime_a.collection_name else runtime_b),
    )
    monkeypatch.setattr(
        retriever_module,
        "build_retrieval_candidate_cache_key",
        lambda **kwargs: cache_key_calls.append(kwargs) or "multi-runtime-cache-key",
    )
    monkeypatch.setattr(
        retriever_module,
        "get_cached_retrieval_candidates",
        lambda key: cache_lookups.append(key) or None,
    )
    monkeypatch.setattr(HybridRetriever, "_search_bm25", lambda self, **kwargs: [])  # noqa: ANN001
    monkeypatch.setattr(HybridRetriever, "_search_lexical_db", lambda self, **kwargs: [])  # noqa: ANN001
    monkeypatch.setattr(HybridRetriever, "_search_sparse", lambda self, **kwargs: [])  # noqa: ANN001

    scope = (
        {"dataset_ids": [dataset_b, dataset_a]}
        if scope_kind == "dataset_ids"
        else {"document_ids": [document_b, document_a]}
    )
    retriever = HybridRetriever(
        tenant_id=tenant_id,
        account_id="member-1",
        retrieval_mode=retrieval_mode,
        enable_reranker=False,
        sparse_enabled=False,
        dedup_enabled=False,
        k=2,
        **scope,
    )

    results = retriever._hybrid_search(
        "scope query",
        top_k=2,
        score_threshold=0.0,
        document_ids=retriever.document_ids,
        tenant_id=tenant_id,
        retrieval_mode=retrieval_mode,
    )

    assert [item["content"] for item in results] == ["runtime a hit"]
    assert [call["collection"] for call in search_calls] == [
        runtime_a.collection_name,
        runtime_b.collection_name,
    ]
    expected_document_filter = (
        {"document_id": {"$in": [str(document_b), str(document_a)]}}
        if scope_kind == "document_ids"
        else {}
    )
    assert search_calls[0]["metadata_filter"] == {
        "tenant_id": str(tenant_id),
        "dataset_id": str(dataset_a),
        "embedding_space_hash": {"$in": ["space-a", ""]},
        **expected_document_filter,
    }
    assert search_calls[1]["metadata_filter"] == {
        "tenant_id": str(tenant_id),
        "dataset_id": str(dataset_b),
        "embedding_space_hash": {"$in": ["space-b", ""]},
        **expected_document_filter,
    }
    assert cache_lookups == ["multi-runtime-cache-key"]
    assert cache_key_calls[0]["pipeline_key"] == "space-a,space-b"
    assert retriever._last_channel_metrics["cache"].get("skip_reason") is None
    assert retriever._last_channel_metrics["cache"]["semantic"]["skip_reason"] == "multi_runtime_scope"
    assert retriever._last_channel_metrics["retrieval_degraded"] is True
    assert retriever._last_channel_metrics["all_retrieval_channels_failed"] is False
    assert {"channel": "vector", "error_type": "RuntimeError"} in retriever._last_channel_metrics[
        "degraded_reasons"
    ]
    successful_channels = retriever._last_channel_metrics["successful_channels"]
    assert "vector" in successful_channels
    assert "bm25" in successful_channels


def test_metadata_filter_dataset_scope_drives_runtime_shards(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.rag.retriever import HybridRetriever

    _configure_retrieval_test(monkeypatch)
    tenant_id = uuid.uuid4()
    dataset_a = uuid.uuid4()
    dataset_b = uuid.uuid4()
    captured: dict[str, tuple[uuid.UUID, ...]] = {}

    def record_runtime_scope(self, *, tenant_id, dataset_ids=None):  # noqa: ANN001,ARG002
        captured["dataset_ids"] = dataset_ids or ()
        return []

    monkeypatch.setattr(
        HybridRetriever,
        "_resolve_dataset_runtime_shards",
        record_runtime_scope,
    )
    monkeypatch.setattr(HybridRetriever, "_resolve_embedding_runtime", lambda self, *, tenant_id: _embedding_runtime())
    monkeypatch.setattr(HybridRetriever, "_search_bm25", lambda self, **kwargs: [])  # noqa: ANN001
    monkeypatch.setattr(HybridRetriever, "_search_lexical_db", lambda self, **kwargs: [])  # noqa: ANN001
    monkeypatch.setattr(HybridRetriever, "_search_sparse", lambda self, **kwargs: [])  # noqa: ANN001

    retriever = HybridRetriever(
        tenant_id=tenant_id,
        retrieval_mode="vector",
        metadata_filter={"dataset_id": {"$in": [str(dataset_b), str(dataset_a), str(dataset_b)]}},
        enable_reranker=False,
    )
    with pytest.raises(LookupError, match="dataset-scoped embedding runtime unavailable"):
        retriever._hybrid_search(
            "scope query",
            top_k=1,
            score_threshold=0.0,
            tenant_id=tenant_id,
            retrieval_mode="vector",
            metadata_filter=retriever.metadata_filter,
        )

    assert captured["dataset_ids"] == tuple(sorted((dataset_a, dataset_b), key=str))


def test_document_dataset_scope_is_tenant_bound_and_fails_closed_when_incomplete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.retriever as retriever_module
    from app.rag.retriever import HybridRetriever

    tenant_id = uuid.uuid4()
    document_a = uuid.uuid4()
    document_b = uuid.uuid4()
    dataset_id = uuid.uuid4()
    rows = [(document_a, dataset_id), (document_b, None)]

    class _Query:
        def filter(self, *_args, **_kwargs):  # noqa: ANN002,ANN003
            return self

        def all(self):  # noqa: ANN202
            return list(rows)

    class _Session:
        def query(self, *_args, **_kwargs):  # noqa: ANN002,ANN003
            return _Query()

        def close(self) -> None:
            return None

    monkeypatch.setattr(retriever_module, "SessionLocal", _Session)
    retriever = HybridRetriever()

    assert retriever._resolve_document_dataset_scope(
        tenant_id=tenant_id,
        document_ids=[document_b, document_a],
    ) == ((dataset_id,), True)

    rows.pop()
    assert (
        retriever._resolve_document_dataset_scope(
            tenant_id=tenant_id,
            document_ids=[document_b, document_a],
        )
        is None
    )


def test_unresolved_document_scope_does_not_fall_back_to_partial_channels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.retriever as retriever_module
    from app.rag.retriever import HybridRetriever

    _configure_retrieval_test(monkeypatch)
    tenant_id = uuid.uuid4()
    document_id = uuid.uuid4()
    fallback_calls: list[str] = []

    monkeypatch.setattr(
        HybridRetriever,
        "_resolve_document_dataset_scope",
        lambda self, *, tenant_id, document_ids: None,  # noqa: ANN001,ARG005
    )
    monkeypatch.setattr(HybridRetriever, "_resolve_embedding_runtime", lambda self, *, tenant_id: _embedding_runtime())
    monkeypatch.setattr(
        retriever_module,
        "get_vector_store",
        lambda: SimpleNamespace(search=lambda **kwargs: fallback_calls.append("vector") or []),
    )
    monkeypatch.setattr(
        HybridRetriever,
        "_search_bm25",
        lambda self, **kwargs: fallback_calls.append("bm25") or [{"content": "partial", "score": 1.0}],
    )
    monkeypatch.setattr(
        HybridRetriever,
        "_search_lexical_db",
        lambda self, **kwargs: fallback_calls.append("lexical") or [{"content": "partial", "score": 1.0}],
    )

    retriever = HybridRetriever(
        tenant_id=tenant_id,
        document_ids=[document_id],
        retrieval_mode="hybrid",
        enable_reranker=False,
        sparse_enabled=False,
        dedup_enabled=False,
    )
    with pytest.raises(LookupError, match="dataset-scoped embedding runtime unavailable"):
        retriever._hybrid_search(
            "scope query",
            top_k=1,
            score_threshold=0.0,
            document_ids=[document_id],
            tenant_id=tenant_id,
            retrieval_mode="hybrid",
        )

    assert fallback_calls == []
    assert retriever._last_channel_metrics["degraded_reasons"] == [
        {"channel": "scope", "error_type": "LookupError"}
    ]
    assert retriever._last_channel_metrics["all_retrieval_channels_failed"] is True


def test_partial_retrieval_failure_returns_results_and_marks_debug(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    retriever, vector_store = _retriever(monkeypatch)

    def fail_vector(**kwargs):  # noqa: ANN003
        raise ConnectionError("milvus unavailable")

    vector_store.search = fail_vector
    monkeypatch.setattr(
        type(retriever),
        "_search_bm25",
        lambda self, **kwargs: [
            {
                "chunk_id": "chunk-1",
                "content": "fallback result",
                "score": 0.8,
                "metadata": {"document_id": "doc-1"},
            }
        ],
    )

    docs = retriever.invoke("fallback query")

    assert [doc.page_content for doc in docs] == ["fallback result"]
    assert retriever._last_debug_metrics["retrieval_degraded"] is True
    assert retriever._last_debug_metrics["retrieval_degraded_reasons"] == [
        {"channel": "vector", "error_type": "ConnectionError"}
    ]
    assert retriever._last_debug_metrics["all_retrieval_channels_failed"] is False


def test_degraded_retrieval_is_not_written_to_candidate_caches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.retriever as retriever_module
    import app.services.semantic_cache as semantic_cache_module
    from app.core.config import settings
    from app.rag.retriever import HybridRetriever

    _configure_retrieval_test(monkeypatch)
    for name, value in {
        "LEXICAL_DB_ENABLED": False,
        "RETRIEVAL_CANDIDATE_CACHE_ENABLED": True,
        "RETRIEVAL_CANDIDATE_CACHE_TTL_SEC": 60,
        "SEMANTIC_CACHE_ENABLED": True,
        "SEMANTIC_CACHE_TTL_SEC": 60,
    }.items():
        monkeypatch.setattr(settings, name, value, raising=False)

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    document_id = uuid.uuid4()
    runtime = _embedding_runtime()
    exact_stores: list[object] = []
    semantic_stores: list[object] = []

    def fail_vector(**_kwargs):  # noqa: ANN003,ANN202
        raise ConnectionError("milvus unavailable")

    monkeypatch.setattr(
        HybridRetriever,
        "_resolve_dataset_runtime_shards",
        lambda self, *, tenant_id, dataset_ids=None: [(runtime, (dataset_id,))],  # noqa: ANN001,ARG005
    )
    monkeypatch.setattr(HybridRetriever, "_resolve_embedding_runtime", lambda self, *, tenant_id: runtime)
    monkeypatch.setattr(
        HybridRetriever,
        "_resolve_candidate_cache_corpus_token",
        lambda self, **kwargs: "corpus-token",  # noqa: ANN001,ARG005
    )
    monkeypatch.setattr(retriever_module, "get_vector_store", lambda: SimpleNamespace(search=fail_vector))
    monkeypatch.setattr(retriever_module, "get_cached_retrieval_candidates", lambda _key: None)
    monkeypatch.setattr(
        retriever_module,
        "set_cached_retrieval_candidates",
        lambda *args, **kwargs: exact_stores.append((args, kwargs)) or True,
    )
    monkeypatch.setattr(semantic_cache_module, "get_cached_semantic_payload", lambda **kwargs: (None, {}))
    monkeypatch.setattr(
        semantic_cache_module,
        "set_cached_semantic_payload",
        lambda **kwargs: semantic_stores.append(kwargs) or True,
    )
    monkeypatch.setattr(
        HybridRetriever,
        "_search_bm25",
        lambda self, **kwargs: [  # noqa: ANN001,ARG005
            {
                "chunk_id": "chunk-1",
                "content": "fallback result",
                "score": 0.8,
                "metadata": {"document_id": str(document_id), "dataset_id": str(dataset_id)},
            }
        ],
    )
    monkeypatch.setattr(HybridRetriever, "_search_lexical_db", lambda self, **kwargs: [])  # noqa: ANN001

    results = HybridRetriever(
        tenant_id=tenant_id,
        account_id="member-1",
        dataset_id=dataset_id,
        document_ids=[document_id],
        retrieval_mode="hybrid",
        enable_reranker=False,
        sparse_enabled=False,
        dedup_enabled=False,
    )._hybrid_search(
        "fallback query",
        top_k=1,
        score_threshold=0.0,
        tenant_id=tenant_id,
        document_ids=[document_id],
        retrieval_mode="hybrid",
    )

    assert [item["content"] for item in results] == ["fallback result"]
    assert exact_stores == []
    assert semantic_stores == []


def test_retrieval_behavior_changes_cache_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.retriever as retriever_module
    from app.core.config import settings
    from app.rag.retriever import HybridRetriever, HybridSearchOptions, _build_retrieval_cache_behavior_hash

    retriever = HybridRetriever(enable_reranker=False)
    behavior1 = _build_retrieval_cache_behavior_hash(
        retriever=retriever,
        options=HybridSearchOptions(vector_weight=0.6),
    )
    behavior2 = _build_retrieval_cache_behavior_hash(
        retriever=retriever,
        options=HybridSearchOptions(vector_weight=0.7),
    )
    monkeypatch.setattr(settings, "LEXICAL_DB_ENABLED", not settings.LEXICAL_DB_ENABLED)
    behavior3 = _build_retrieval_cache_behavior_hash(
        retriever=retriever,
        options=HybridSearchOptions(vector_weight=0.6),
    )
    first_document_id = uuid.uuid4()
    second_document_id = uuid.uuid4()
    ordered_scope = _build_retrieval_cache_behavior_hash(
        retriever=retriever,
        options=HybridSearchOptions(document_ids=[first_document_id, second_document_id]),
    )
    reversed_scope = _build_retrieval_cache_behavior_hash(
        retriever=retriever,
        options=HybridSearchOptions(document_ids=[second_document_id, first_document_id]),
    )

    assert behavior1 != behavior2
    assert behavior1 != behavior3
    assert ordered_scope == reversed_scope

    base_kwargs = {
        "tenant_id": "tenant-1",
        "account_id": "account-1",
        "dataset_id": "dataset-1",
        "pipeline_key": "space-1",
        "corpus_cache_token": "corpus-1",
        "query": "what is the capex budget",
        "top_k": 8,
        "score_threshold": 0.6,
        "retrieval_mode": "hybrid",
        "metadata_filter": {"tenant_id": "tenant-1"},
        "document_ids": ["doc-1", "doc-2"],
    }
    key1 = retriever_module.build_retrieval_candidate_cache_key(
        behavior_hash=behavior1,
        **base_kwargs,
    )
    key2 = retriever_module.build_retrieval_candidate_cache_key(
        behavior_hash=behavior2,
        **base_kwargs,
    )
    assert key1 != key2


def test_hybrid_search_propagates_behavior_hash_to_retrieval_and_semantic_cache_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.retriever as retriever_module
    import app.services.semantic_cache as semantic_cache_module
    from app.core.config import settings
    from app.rag.retriever import HybridRetriever

    _configure_retrieval_test(monkeypatch)
    for name, value in {
        "RETRIEVAL_CANDIDATE_CACHE_ENABLED": True,
        "RETRIEVAL_CANDIDATE_CACHE_TTL_SEC": 60,
        "SEMANTIC_CACHE_ENABLED": True,
        "SEMANTIC_CACHE_TTL_SEC": 60,
        "RERANK_PROFILE": "default",
        "RERANKER_PROVIDER": "llm",
    }.items():
        monkeypatch.setattr(settings, name, value, raising=False)

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    runtime = _embedding_runtime()
    doc_id = uuid.uuid4()
    get_calls: list[object] = []
    set_calls: list[object] = []
    key_calls: list[dict[str, object]] = []

    monkeypatch.setattr(
        HybridRetriever,
        "_resolve_dataset_runtime_shards",
        lambda self, *, tenant_id, dataset_ids=None: [(runtime, (dataset_id,))],  # noqa: ANN001,ARG005
    )
    monkeypatch.setattr(HybridRetriever, "_resolve_embedding_runtime", lambda self, *, tenant_id: runtime)
    monkeypatch.setattr(
        HybridRetriever,
        "_resolve_candidate_cache_corpus_token",
        lambda self, **kwargs: "corpus-token",  # noqa: ANN001,ARG005
    )
    monkeypatch.setattr(
        retriever_module,
        "get_vector_store",
        lambda: SimpleNamespace(search=lambda **kwargs: []),  # noqa: ARG005
    )
    monkeypatch.setattr(
        HybridRetriever,
        "_search_bm25",
        lambda self, **kwargs: [  # noqa: ANN001,ARG005
            {
                "chunk_id": "chunk-1",
                "content": "cacheable result",
                "score": 0.9,
                "metadata": {"document_id": str(doc_id), "dataset_id": str(dataset_id)},
            }
        ],
    )
    monkeypatch.setattr(HybridRetriever, "_search_lexical_db", lambda self, **kwargs: [])  # noqa: ANN001
    monkeypatch.setattr(
        retriever_module,
        "build_retrieval_candidate_cache_key",
        lambda **kwargs: key_calls.append(kwargs) or "cache-key",
    )
    monkeypatch.setattr(
        retriever_module,
        "get_cached_retrieval_candidates",
        lambda _key: None,
    )
    monkeypatch.setattr(retriever_module, "set_cached_retrieval_candidates", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        semantic_cache_module,
        "get_cached_semantic_payload",
        lambda **kwargs: get_calls.append(kwargs) or (None, {}),
    )
    monkeypatch.setattr(
        semantic_cache_module,
        "set_cached_semantic_payload",
        lambda **kwargs: set_calls.append(kwargs) or True,
    )

    retriever = HybridRetriever(
        tenant_id=tenant_id,
        account_id="member-1",
        dataset_id=dataset_id,
        dataset_ids=[dataset_id],
        retrieval_mode="hybrid",
        enable_reranker=False,
        sparse_enabled=False,
        dedup_enabled=False,
    )
    retriever._hybrid_search(
        "what is a budget",
        top_k=1,
        score_threshold=0.0,
        tenant_id=tenant_id,
        retrieval_mode="hybrid",
    )

    assert len(key_calls) == 1
    assert len(get_calls) == 1
    assert len(set_calls) == 1
    behavior_hash = key_calls[0]["behavior_hash"]
    assert isinstance(behavior_hash, str) and behavior_hash
    assert get_calls[0]["behavior_hash"] == behavior_hash
    assert set_calls[0]["behavior_hash"] == behavior_hash


def test_retrieval_candidate_cache_singleflight_coalesces_concurrent_exact_misses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.retriever as retriever_module
    from app.core.config import settings
    from app.rag.retrieval_candidate_cache import clear_inflight_retrieval_candidates
    from app.rag.retriever import HybridRetriever

    _configure_retrieval_test(monkeypatch)
    for name, value in {
        "RETRIEVAL_CANDIDATE_CACHE_ENABLED": True,
        "RETRIEVAL_CANDIDATE_CACHE_TTL_SEC": 60,
        "SEMANTIC_CACHE_ENABLED": False,
    }.items():
        monkeypatch.setattr(settings, name, value, raising=False)

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    document_id = uuid.uuid4()
    runtime = _embedding_runtime()
    search_started = threading.Event()
    release_search = threading.Event()
    search_calls = 0
    search_lock = threading.Lock()
    results: list[list[dict[str, object]]] = []
    errors: list[Exception] = []

    def search(**_kwargs):  # noqa: ANN003,ANN202
        nonlocal search_calls
        with search_lock:
            search_calls += 1
        search_started.set()
        release_search.wait(timeout=2.0)
        return [
            {
                "chunk_id": "chunk-1",
                "content": "singleflight result",
                "score": 0.92,
                "metadata": {
                    "chunk_id": "chunk-1",
                    "document_id": str(document_id),
                    "dataset_id": str(dataset_id),
                    "embedding_space_hash": runtime.embedding_space_hash,
                },
            }
        ]

    monkeypatch.setattr(
        HybridRetriever,
        "_resolve_dataset_runtime_shards",
        lambda self, *, tenant_id, dataset_ids=None: [(runtime, (dataset_id,))],  # noqa: ANN001,ARG005
    )
    monkeypatch.setattr(HybridRetriever, "_resolve_embedding_runtime", lambda self, *, tenant_id: runtime)
    monkeypatch.setattr(
        HybridRetriever,
        "_resolve_candidate_cache_corpus_token",
        lambda self, **kwargs: "corpus-token",  # noqa: ANN001,ARG005
    )
    monkeypatch.setattr(HybridRetriever, "_enrich_results_with_db_metadata", lambda self, items, **kwargs: list(items))
    monkeypatch.setattr(HybridRetriever, "_expand_results_with_neighbors", lambda self, items: list(items))
    monkeypatch.setattr(HybridRetriever, "_auto_merge_parent_child", lambda self, items: list(items))
    monkeypatch.setattr(retriever_module, "get_vector_store", lambda: SimpleNamespace(search=search))
    monkeypatch.setattr(retriever_module, "get_cached_retrieval_candidates", lambda _key: None)
    monkeypatch.setattr(retriever_module, "set_cached_retrieval_candidates", lambda *args, **kwargs: True)
    monkeypatch.setattr(HybridRetriever, "_search_bm25", lambda self, **kwargs: [])  # noqa: ANN001
    monkeypatch.setattr(HybridRetriever, "_search_lexical_db", lambda self, **kwargs: [])  # noqa: ANN001
    monkeypatch.setattr(HybridRetriever, "_search_sparse", lambda self, **kwargs: [])  # noqa: ANN001

    def run_search() -> None:
        retriever = HybridRetriever(
            tenant_id=tenant_id,
            account_id="member-1",
            dataset_id=dataset_id,
            document_ids=[document_id],
            retrieval_mode="vector",
            enable_reranker=False,
            sparse_enabled=False,
            dedup_enabled=False,
        )
        try:
            results.append(
                retriever._hybrid_search(
                    "singleflight query",
                    top_k=1,
                    score_threshold=0.0,
                    tenant_id=tenant_id,
                    document_ids=[document_id],
                    retrieval_mode="vector",
                )
            )
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    clear_inflight_retrieval_candidates()
    try:
        threads = [threading.Thread(target=run_search), threading.Thread(target=run_search)]
        for thread in threads:
            thread.start()

        assert search_started.wait(timeout=1.0)
        time.sleep(0.1)
        with search_lock:
            assert search_calls == 1

        release_search.set()
        for thread in threads:
            thread.join(timeout=2.0)

        assert errors == []
        assert search_calls == 1
        assert len(results) == 2
        assert all([item["content"] for item in payload] == ["singleflight result"] for payload in results)
        assert results[0][0] is not results[1][0]
    finally:
        release_search.set()
        clear_inflight_retrieval_candidates()


def test_retrieval_candidate_cache_singleflight_wait_timeout_releases_key_without_cancelling_leader() -> None:
    from app.rag.retrieval_candidate_cache import (
        acquire_inflight_retrieval_candidates,
        clear_inflight_retrieval_candidates,
        wait_for_inflight_retrieval_candidates,
    )

    clear_inflight_retrieval_candidates()
    try:
        leader, future = acquire_inflight_retrieval_candidates("cache-key")
        assert leader is True

        follower, shared_future = acquire_inflight_retrieval_candidates("cache-key")
        assert follower is False
        assert shared_future is future

        with pytest.raises(TimeoutError, match="singleflight timed out"):
            wait_for_inflight_retrieval_candidates("cache-key", shared_future, timeout_sec=0.01)

        leader_again, _future_again = acquire_inflight_retrieval_candidates("cache-key")
        assert leader_again is True
        assert future.cancelled() is False
        future.set_result([{"chunk_id": "leader-result"}])
        assert future.result() == [{"chunk_id": "leader-result"}]
    finally:
        clear_inflight_retrieval_candidates()


def test_hybrid_search_wrapper_rejects_current_inflight_on_impl_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.retriever as retriever_module
    from app.rag.retrieval_candidate_cache import (
        acquire_inflight_retrieval_candidates,
        clear_inflight_retrieval_candidates,
    )
    from app.rag.retriever import HybridRetriever

    calls: list[str] = []

    def fail_impl(self, query: str, *, options=None, embedding_runtime=None, **legacy_overrides):  # noqa: ANN001,ARG001
        leader, _future = acquire_inflight_retrieval_candidates("cache-key")
        assert leader is True
        raise RuntimeError("leader failed")

    monkeypatch.setattr(retriever_module, "reject_current_inflight_retrieval_candidates", lambda exc: calls.append(str(exc)))
    monkeypatch.setattr(HybridRetriever, "_hybrid_search_impl", fail_impl)

    clear_inflight_retrieval_candidates()
    try:
        with pytest.raises(RuntimeError, match="leader failed"):
            HybridRetriever()._hybrid_search("query")
        assert calls == ["leader failed"]
    finally:
        clear_inflight_retrieval_candidates()


def test_all_retrieval_failures_build_engine_error_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.rag.engine import _retrieval_error_from_debug

    retriever, vector_store = _retriever(monkeypatch)

    def fail_vector(**kwargs):  # noqa: ANN003
        raise ConnectionError("milvus unavailable")

    def fail_bm25(self, **kwargs):  # noqa: ANN001,ANN003
        raise RuntimeError("bm25 unavailable")

    vector_store.search = fail_vector
    monkeypatch.setattr(type(retriever), "_search_bm25", fail_bm25)

    assert retriever.invoke("failed query") == []
    debug = retriever._last_debug_metrics
    assert debug["all_retrieval_channels_failed"] is True
    assert _retrieval_error_from_debug(debug) == (
        "all retrieval channels failed: bm25:RuntimeError, vector:ConnectionError"
    )


def test_zero_hit_is_not_marked_as_degraded(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.rag.engine import _retrieval_error_from_debug

    retriever, _vector_store = _retriever(monkeypatch)
    monkeypatch.setattr(type(retriever), "_search_bm25", lambda self, **kwargs: [])

    assert retriever.invoke("zero hit query") == []
    debug = retriever._last_debug_metrics
    assert debug["retrieval_degraded"] is False
    assert debug["retrieval_degraded_reasons"] == []
    assert debug["all_retrieval_channels_failed"] is False
    assert _retrieval_error_from_debug(debug) is None


@pytest.mark.asyncio
async def test_worker_heartbeat_survives_transient_observation_failure() -> None:
    from app.tasks.worker import _heartbeat_loop

    calls = 0
    recovered = asyncio.Event()

    async def observe(**kwargs):  # noqa: ANN003
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ConnectionError("redis unavailable")
        recovered.set()

    task = asyncio.create_task(
        _heartbeat_loop(
            redis=object(),
            queue_name="test",
            worker_id="worker-1",
            interval=0,
            observe=observe,
        )
    )
    try:
        await asyncio.wait_for(recovered.wait(), timeout=0.5)
        assert calls >= 2
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_worker_startup_registers_heartbeat_task(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.tasks.worker as worker

    async def wait_forever(**_kwargs):  # noqa: ANN003, ANN202
        await asyncio.Event().wait()

    monkeypatch.setattr(worker, "_heartbeat_loop", wait_forever)
    ctx = {"redis": object()}

    await worker.startup(ctx)
    assert worker._WORKER_HEARTBEAT_TASK_KEY in ctx
    await worker.shutdown(ctx)


def test_bm25_concurrent_first_build_uses_one_scope_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.retriever as retriever_module
    from app.core.config import settings
    from app.rag.retriever import HybridRetriever

    retriever = HybridRetriever(document_ids=[uuid.uuid4()])
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    factory_barrier = threading.Barrier(2)
    call_barrier = threading.Barrier(2)
    state_lock = threading.Lock()
    build_count = 0
    built = False

    def lock_factory():
        factory_barrier.wait(timeout=1)
        return threading.Lock()

    def build_inside_lock(self, **kwargs):  # noqa: ANN001,ANN003
        nonlocal build_count, built
        with state_lock:
            if built:
                return True
            build_count += 1
        time.sleep(0.05)
        with state_lock:
            built = True
        return True

    monkeypatch.setattr(settings, "BM25_INDEX_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "BM25_LAZY_BUILD_ENABLED", True, raising=False)
    monkeypatch.setattr(retriever_module, "threading", SimpleNamespace(Lock=lock_factory))
    monkeypatch.setattr(HybridRetriever, "_bm25_existing_scope_ready", lambda self, **kwargs: False)
    monkeypatch.setattr(HybridRetriever, "_build_bm25_scope_inside_lock", build_inside_lock)

    results: list[bool] = []

    def build() -> None:
        call_barrier.wait(timeout=1)
        results.append(
            retriever._lazy_build_bm25_index(
                tenant_id=tenant_id,
                document_ids=None,
                dataset_ids=(dataset_id,),
            )
        )

    threads = [threading.Thread(target=build) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)

    assert not any(thread.is_alive() for thread in threads)
    assert results == [True, True]
    assert build_count == 1


def test_bm25_multi_dataset_scope_stays_bounded_and_invalidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from langchain_core.documents import Document

    import app.rag.retriever as retriever_module
    from app.core.config import settings
    from app.rag.retriever import HybridRetriever

    tenant_id = uuid.uuid4()
    dataset_a = uuid.uuid4()
    dataset_b = uuid.uuid4()
    retriever = HybridRetriever(dataset_ids=[dataset_b, dataset_a, dataset_b])
    captured: dict[str, object] = {}

    scope_tenant, dataset_scope_ids, cache_key = retriever._bm25_search_scope(
        tenant_id=tenant_id,
        document_ids=None,
    )

    assert scope_tenant == tenant_id
    assert dataset_scope_ids == tuple(sorted((dataset_a, dataset_b), key=str))
    assert cache_key != str(tenant_id)
    assert cache_key == HybridRetriever(dataset_ids=[dataset_a, dataset_b])._bm25_search_scope(
        tenant_id=tenant_id,
        document_ids=None,
    )[2]

    monkeypatch.setattr(settings, "BM25_INDEX_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "BM25_LAZY_BUILD_ENABLED", True, raising=False)
    monkeypatch.setattr(HybridRetriever, "_bm25_existing_scope_ready", lambda self, **kwargs: False)
    monkeypatch.setattr(
        retriever_module,
        "SessionLocal",
        lambda: SimpleNamespace(close=lambda: None),
        raising=True,
    )

    def load_scope_docs(self, db, **kwargs):  # noqa: ANN001,ARG001
        captured["dataset_ids"] = kwargs["dataset_ids"]
        return [
            Document(
                page_content="scope doc",
                id="chunk-1",
                metadata={
                    "document_id": str(uuid.uuid4()),
                    "chunk_index": 0,
                },
            )
        ]

    def build_index(self, docs, *, tenant_id, cache_key):  # noqa: ANN001
        captured["cache_key"] = cache_key
        captured["docs"] = len(docs)

    monkeypatch.setattr(HybridRetriever, "_load_bm25_scope_documents", load_scope_docs)
    monkeypatch.setattr(HybridRetriever, "_build_bm25_index_from_documents", build_index)

    built = retriever._lazy_build_bm25_index(
        tenant_id=tenant_id,
        document_ids=None,
        dataset_ids=dataset_scope_ids,
    )

    assert built is True
    assert captured["dataset_ids"] == tuple(sorted((dataset_a, dataset_b), key=str))
    assert captured["cache_key"] == retriever._bm25_scope_key(
        tenant_id=tenant_id,
        dataset_ids=dataset_scope_ids,
        document_ids=None,
    )
    assert captured["docs"] == 1

    retriever._bm25_retrievers[cache_key] = object()  # type: ignore[assignment]
    retriever._bm25_docs[cache_key] = [Document(page_content="old", id="old")]
    retriever._bm25_cache_versions[cache_key] = "old-version"

    def dataset_version(self, *, _tenant_id, _dataset_ids):  # noqa: ANN001
        captured["version_dataset_ids"] = _dataset_ids
        return "new-version"

    monkeypatch.setattr(HybridRetriever, "_bm25_dataset_cache_version", dataset_version)

    assert retriever._refresh_bm25_dataset_cache_version(
        cache_key=cache_key,
        tenant_uuid=tenant_id,
        dataset_scope_ids=dataset_scope_ids,
    ) == "new-version"
    assert captured["version_dataset_ids"] == dataset_scope_ids
    assert cache_key not in retriever._bm25_retrievers
    assert cache_key not in retriever._bm25_docs


def test_bm25_database_row_keeps_dataset_scope_metadata() -> None:
    from app.rag.retriever import HybridRetriever

    chunk_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    document_id = uuid.uuid4()
    dataset_id = uuid.uuid4()

    document = HybridRetriever._document_from_chunk_row(
        (chunk_id, "body", {}, tenant_id, document_id, 3, 7, dataset_id),
    )

    assert document.id == str(chunk_id)
    assert document.metadata["dataset_id"] == str(dataset_id)
    assert document.metadata["document_id"] == str(document_id)


def test_bm25_document_scope_cache_key_is_isolated_and_stable() -> None:
    from app.rag.retriever import HybridRetriever

    tenant_id = uuid.uuid4()
    document_a = uuid.uuid4()
    document_b = uuid.uuid4()
    retriever = HybridRetriever()

    tenant_key = retriever._bm25_scope_key(
        tenant_id=tenant_id,
        document_ids=None,
    )
    document_key = retriever._bm25_scope_key(
        tenant_id=tenant_id,
        document_ids=[document_a, document_b],
    )

    assert document_key != tenant_key
    assert document_key != retriever._bm25_scope_key(
        tenant_id=tenant_id,
        document_ids=[document_a],
    )
    assert document_key == retriever._bm25_scope_key(
        tenant_id=tenant_id,
        document_ids=[document_b, document_a, document_b],
    )


def test_bm25_document_scope_caches_are_mutation_scoped(monkeypatch: pytest.MonkeyPatch) -> None:
    from langchain_core.documents import Document

    from app.rag.retriever import HybridRetriever

    tenant_id = uuid.uuid4()
    document_id = uuid.uuid4()
    retriever = HybridRetriever()
    scope_key = f"{tenant_id}:documents:1:cached"
    retriever._bm25_retrievers[scope_key] = object()  # type: ignore[assignment]
    retriever._bm25_docs[scope_key] = [
        Document(
            page_content="old",
            id=str(uuid.uuid4()),
            metadata={"document_id": str(document_id), "chunk_index": 0},
        )
    ]
    retriever._bm25_doc_ids[scope_key] = {str(document_id)}
    retriever._chunk_id_lookup[scope_key] = {}
    retriever._bm25_cache_versions[scope_key] = "old"

    assert scope_key in retriever._bm25_filter_scope_keys(tenant_key=str(tenant_id))

    monkeypatch.setattr(HybridRetriever, "_replace_bm25_scope_index", lambda self, **kwargs: None)
    monkeypatch.setattr(HybridRetriever, "_sync_sparse_index_after_bm25_upsert", lambda self, **kwargs: None)
    monkeypatch.setattr(HybridRetriever, "_sync_colbert_index_after_bm25_upsert", lambda self, **kwargs: None)
    retriever.upsert_bm25_documents(
        [
            Document(
                page_content="new",
                id=str(uuid.uuid4()),
                metadata={"document_id": str(document_id), "chunk_index": 0},
            )
        ],
        tenant_id=tenant_id,
    )

    assert scope_key not in retriever._bm25_retrievers
    assert scope_key not in retriever._bm25_docs
    assert scope_key not in retriever._bm25_doc_ids
    assert scope_key not in retriever._chunk_id_lookup
    assert scope_key not in retriever._bm25_cache_versions


def test_bm25_document_scope_cache_version_invalidates_stale_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from langchain_core.documents import Document

    from app.rag.retriever import HybridRetriever

    tenant_id = uuid.uuid4()
    document_id = uuid.uuid4()
    retriever = HybridRetriever()
    scope_key = retriever._bm25_scope_key(
        tenant_id=tenant_id,
        document_ids=[document_id],
    )
    retriever._bm25_retrievers[scope_key] = object()  # type: ignore[assignment]
    retriever._bm25_docs[scope_key] = [Document(page_content="old", id=str(uuid.uuid4()))]
    retriever._bm25_cache_versions[scope_key] = "old-version"
    monkeypatch.setattr(
        HybridRetriever,
        "_resolve_candidate_cache_corpus_token",
        lambda self, **kwargs: "new-version",
    )

    assert retriever._refresh_bm25_dataset_cache_version(
        cache_key=scope_key,
        tenant_uuid=tenant_id,
        dataset_scope_ids=(),
        document_ids=[document_id],
    ) == "new-version"
    assert scope_key not in retriever._bm25_retrievers
    assert scope_key not in retriever._bm25_docs


def test_candidate_corpus_token_reuses_short_lived_lookup_and_invalidates_on_upsert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from langchain_core.documents import Document

    import app.rag.retriever as retriever_module
    from app.rag.retriever import HybridRetriever

    calls = 0

    class _Session:
        def close(self) -> None:
            return None

    def resolve_token(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        nonlocal calls
        calls += 1
        return f"version-{calls}"

    monkeypatch.setattr(retriever_module, "SessionLocal", lambda: _Session(), raising=True)
    monkeypatch.setattr(retriever_module, "resolve_corpus_cache_token", resolve_token, raising=True)
    clock = [0.0]
    monkeypatch.setattr(retriever_module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(HybridRetriever, "_replace_bm25_scope_index", lambda self, **kwargs: None)
    monkeypatch.setattr(HybridRetriever, "_sync_sparse_index_after_bm25_upsert", lambda self, **kwargs: None)
    monkeypatch.setattr(HybridRetriever, "_sync_colbert_index_after_bm25_upsert", lambda self, **kwargs: None)

    tenant_id = uuid.uuid4()
    document_id = uuid.uuid4()
    retriever = HybridRetriever(tenant_id=tenant_id)

    assert retriever._resolve_candidate_cache_corpus_token(
        tenant_id=tenant_id,
        document_ids=[document_id],
    ) == "version-1"
    assert retriever._resolve_candidate_cache_corpus_token(
        tenant_id=tenant_id,
        document_ids=[document_id],
    ) == "version-1"

    retriever.upsert_bm25_documents(
        [
            Document(
                page_content="updated",
                id=str(uuid.uuid4()),
                metadata={"document_id": str(document_id), "chunk_index": 0},
            )
        ],
        tenant_id=tenant_id,
    )

    assert retriever._resolve_candidate_cache_corpus_token(
        tenant_id=tenant_id,
        document_ids=[document_id],
    ) == "version-2"
    clock[0] = 2.0
    assert retriever._resolve_candidate_cache_corpus_token(
        tenant_id=tenant_id,
        document_ids=[document_id],
    ) == "version-3"
    assert calls == 3


def test_candidate_corpus_token_resolves_multi_dataset_scope_without_document_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.retriever as retriever_module
    from app.rag.retriever import HybridRetriever

    captured: dict[str, object] = {}

    class _Session:
        def close(self) -> None:
            return None

    def resolve_token(*_args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        captured.update(kwargs)
        return "multi-dataset-token"

    tenant_id = uuid.uuid4()
    dataset_a = uuid.uuid4()
    dataset_b = uuid.uuid4()
    monkeypatch.setattr(retriever_module, "SessionLocal", lambda: _Session(), raising=True)
    monkeypatch.setattr(retriever_module, "resolve_corpus_cache_token", resolve_token, raising=True)

    token = HybridRetriever(tenant_id=tenant_id, dataset_ids=[dataset_b, dataset_a, dataset_b])._resolve_candidate_cache_corpus_token(
        tenant_id=tenant_id,
        document_ids=None,
    )

    assert token == "multi-dataset-token"
    assert captured["tenant_id"] == tenant_id
    assert captured["dataset_id"] is None
    assert captured["dataset_ids"] == tuple(sorted((dataset_a, dataset_b), key=str))
    assert captured["document_ids"] == []


def test_bm25_unversioned_existing_scope_is_rebuilt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from langchain_core.documents import Document

    from app.rag.retriever import HybridRetriever

    tenant_id = uuid.uuid4()
    document_id = uuid.uuid4()
    retriever = HybridRetriever()
    scope_key = retriever._bm25_scope_key(
        tenant_id=tenant_id,
        document_ids=[document_id],
    )
    retriever._bm25_retrievers[scope_key] = object()  # type: ignore[assignment]
    retriever._bm25_docs[scope_key] = [Document(page_content="unknown-version", id=str(uuid.uuid4()))]
    monkeypatch.setattr(
        HybridRetriever,
        "_resolve_candidate_cache_corpus_token",
        lambda self, **kwargs: "current-version",
    )

    assert retriever._refresh_bm25_dataset_cache_version(
        cache_key=scope_key,
        tenant_uuid=tenant_id,
        dataset_scope_ids=(),
        document_ids=[document_id],
    ) == "current-version"
    assert scope_key not in retriever._bm25_retrievers
    assert scope_key not in retriever._bm25_docs
    assert scope_key not in retriever._bm25_cache_versions


def test_bm25_document_scope_cache_rebuilds_when_requested_document_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from langchain_core.documents import Document

    from app.rag.retriever import HybridRetriever

    tenant_id = uuid.uuid4()
    document_a = uuid.uuid4()
    document_b = uuid.uuid4()
    retriever = HybridRetriever()
    scope_key = retriever._bm25_scope_key(
        tenant_id=tenant_id,
        document_ids=[document_a, document_b],
    )
    old_retriever = object()
    new_retriever = object()
    old_docs = [
        Document(
            page_content="a",
            id=str(uuid.uuid4()),
            metadata={"document_id": str(document_a)},
        )
    ]
    new_docs = old_docs + [
        Document(
            page_content="b",
            id=str(uuid.uuid4()),
            metadata={"document_id": str(document_b)},
        )
    ]
    retriever._bm25_retrievers[scope_key] = old_retriever  # type: ignore[assignment]
    retriever._bm25_docs[scope_key] = old_docs

    def rebuild(self, **kwargs):  # noqa: ANN001, ANN202
        self._bm25_retrievers[scope_key] = new_retriever
        self._bm25_docs[scope_key] = new_docs
        return True

    monkeypatch.setattr(HybridRetriever, "_lazy_build_bm25_index", rebuild)

    cached_retriever, cached_docs = retriever._ensure_bm25_search_index(
        cache_key=scope_key,
        tenant_uuid=tenant_id,
        dataset_scope_ids=(),
        document_ids=[document_a, document_b],
    )

    assert cached_retriever is new_retriever
    assert cached_docs == new_docs
    assert retriever._last_bm25_status["reason"] == "lazy_build_success"


def test_enrich_results_fails_closed_when_acl_lookup_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.retriever as retriever_module
    from app.rag.retriever import HybridRetriever

    class _Session:
        def query(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            raise RuntimeError("database unavailable")

        def close(self) -> None:
            return None

    monkeypatch.setattr(retriever_module, "SessionLocal", lambda: _Session(), raising=True)
    monkeypatch.setattr(
        HybridRetriever,
        "_resolve_embedding_runtime",
        lambda self, *, tenant_id: _embedding_runtime(),
    )
    stats: dict[str, object] = {}

    results = HybridRetriever(tenant_id=uuid.uuid4())._enrich_results_with_db_metadata(
        [
            {
                "chunk_id": str(uuid.uuid4()),
                "content": "must not escape without ACL validation",
                "metadata": {},
            }
        ],
        stats=stats,
    )

    assert results == []
    assert stats["output_results"] == 0
    assert stats["exception"] == "database unavailable"


def test_enrich_results_fails_closed_when_metadata_filter_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.core.filters as filters_module
    import app.rag.retriever as retriever_module
    from app.rag.retriever import HybridRetriever

    monkeypatch.setattr(
        retriever_module,
        "SessionLocal",
        lambda: SimpleNamespace(close=lambda: None),
        raising=True,
    )
    monkeypatch.setattr(
        filters_module,
        "apply_metadata_filter_with_stats",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("filter unavailable")),
    )
    stats: dict[str, object] = {}

    results = HybridRetriever(metadata_filter={"region": "east"})._enrich_results_with_db_metadata(
        [{"content": "must not escape a failed final filter", "metadata": {"region": "east"}}],
        stats=stats,
        embedding_runtime=_embedding_runtime(),
    )

    assert results == []
    assert stats["output_results"] == 0
    assert stats["exception"] == "filter unavailable"


def test_chunk_mutations_rotate_document_corpus_version_before_commit() -> None:
    from pathlib import Path

    source = Path("app/api/v1/document_chunks_write.py").read_text(encoding="utf-8")
    version_touch = "document.updated_at = datetime.now(UTC)"
    for function_name, next_decorator in (
        ("create_document_chunk", "@router.patch("),
        ("patch_document_chunk", "@router.delete("),
        ("delete_document_chunk", "@router.post("),
        ("disable_document_chunk", "@router.post("),
        ("enable_document_chunk", "@router.post("),
    ):
        function_start = source.index(f"async def {function_name}(")
        function_source = source[function_start : source.index(next_decorator, function_start)]
        assert version_touch in function_source
        assert function_source.index(version_touch) < function_source.index("db.commit()")


def test_drift_replay_disable_rotates_document_corpus_version_before_commit() -> None:
    from pathlib import Path

    source = Path("app/services/index_audit_service.py").read_text(encoding="utf-8")
    function_start = source.index("def _finalize_chunk_disable(")
    function_source = source[function_start : source.index("def _finalize_chunk_delete(", function_start)]
    version_touch = "document.updated_at = datetime.now(UTC)"

    assert "document: DBDocument | None" in function_source
    assert version_touch in function_source
    assert function_source.index(version_touch) < function_source.index("db.commit()")
    assert "_finalize_chunk_disable(db=db, document=document, chunk=chunk)" in source


def test_enrich_results_uses_hit_expected_embedding_space_for_multi_runtime_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.retriever as retriever_module
    from app.rag.retriever import HybridRetriever

    tenant_id = uuid.uuid4()
    dataset_a = uuid.uuid4()
    dataset_b = uuid.uuid4()
    document_a = uuid.uuid4()
    document_b = uuid.uuid4()
    document_unknown = uuid.uuid4()
    expected_key = retriever_module._RETRIEVAL_EXPECTED_EMBEDDING_SPACE_KEY
    chunk_a = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        document_id=document_a,
        chunk_index=0,
        content="chunk-a",
        doc_metadata={"embedding_space_hash": "space-a"},
        page_number=None,
        start_char=None,
        end_char=None,
        disabled_at=None,
    )
    chunk_b = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        document_id=document_b,
        chunk_index=0,
        content="chunk-b",
        doc_metadata={"embedding_space_hash": "space-b"},
        page_number=None,
        start_char=None,
        end_char=None,
        disabled_at=None,
    )
    chunk_unknown = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        document_id=document_unknown,
        chunk_index=0,
        content="chunk-unknown",
        doc_metadata={},
        page_number=None,
        start_char=None,
        end_char=None,
        disabled_at=None,
    )
    document_rows = [
        (document_a, "a.md", dataset_a, "completed", {}, None, None, "published", 0, None, None, None),
        (document_b, "b.md", dataset_b, "completed", {}, None, None, "published", 0, None, None, None),
        (document_unknown, "unknown.md", dataset_a, "completed", {}, None, None, "published", 0, None, None, None),
    ]

    class _Query:
        def __init__(self, rows) -> None:  # noqa: ANN001
            self.rows = rows

        def filter(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
            return self

        def all(self):  # noqa: ANN202
            return list(self.rows)

    class _Session:
        def __init__(self) -> None:
            self._rows = [
                [chunk_a, chunk_b, chunk_unknown],
                document_rows,
                [],
            ]

        def query(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
            return _Query(self._rows.pop(0))

        def close(self) -> None:
            return None

    monkeypatch.setattr(retriever_module, "SessionLocal", lambda: _Session(), raising=True)
    retriever = HybridRetriever(tenant_id=tenant_id, dataset_ids=[dataset_a, dataset_b])
    stats: dict[str, int | str | None] = {}

    enriched = retriever._enrich_results_with_db_metadata(
        [
            {
                "content": "stale-a",
                "score": 0.9,
                "metadata": {
                    "document_id": str(document_a),
                    "chunk_index": 0,
                    expected_key: "space-a",
                },
            },
            {
                "content": "stale-b",
                "score": 0.8,
                "metadata": {
                    "document_id": str(document_b),
                    "chunk_index": 0,
                    expected_key: "space-a",
                },
            },
            {
                "content": "bm25-b",
                "score": 0.7,
                "metadata": {
                    "document_id": str(document_b),
                    "chunk_index": 0,
                },
            },
            {
                "content": "legacy-unknown",
                "score": 0.6,
                "metadata": {
                    "document_id": str(document_unknown),
                    "chunk_index": 0,
                    expected_key: "space-a",
                },
            },
        ],
        stats=stats,
        embedding_runtime=_embedding_runtime(),
    )

    assert [item["metadata"]["document_id"] for item in enriched] == [str(document_a), str(document_b)]
    assert enriched[0]["content"] == "chunk-a"
    assert enriched[1]["content"] == "chunk-b"
    assert stats["filtered_embedding_space"] == 2
    assert stats["output_results"] == 2


def test_missing_dataset_runtime_rows_fail_closed_instead_of_falling_back_global(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.retriever as retriever_module
    from app.rag.retriever import HybridRetriever

    _configure_retrieval_test(monkeypatch)
    monkeypatch.setattr(retriever_module.settings, "RETRIEVAL_CANDIDATE_CACHE_ENABLED", True)
    monkeypatch.setattr(retriever_module.settings, "SEMANTIC_CACHE_ENABLED", True)
    monkeypatch.setattr(retriever_module.settings, "RETRIEVAL_CANDIDATE_CACHE_TTL_SEC", 60)
    monkeypatch.setattr(retriever_module.settings, "SEMANTIC_CACHE_TTL_SEC", 60)

    tenant_id = uuid.uuid4()
    dataset_a = uuid.uuid4()
    dataset_b = uuid.uuid4()

    class _Query:
        def filter(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
            return self

        def all(self):  # noqa: ANN202
            return [(dataset_a, {"embedding_defaults": {"provider": "local", "model": "model-a"}})]

    class _Session:
        def query(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
            return _Query()

        def close(self) -> None:
            return None

    monkeypatch.setattr(retriever_module, "SessionLocal", lambda: _Session(), raising=True)
    with pytest.raises(LookupError, match="dataset-scoped embedding runtime unavailable"):
        HybridRetriever(dataset_ids=[dataset_a, dataset_b])._resolve_dataset_runtime_shards(
            tenant_id=tenant_id,
        )


def test_mixed_default_and_dataset_scoped_runtime_shards_use_native_search_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.retriever as retriever_module
    from app.rag.retriever import HybridRetriever
    from app.services.dataset_embedding_config import DatasetEmbeddingRuntimeConfig

    _configure_retrieval_test(monkeypatch)
    tenant_id = uuid.uuid4()
    dataset_a = uuid.uuid4()
    dataset_b = uuid.uuid4()
    runtime_default = DatasetEmbeddingRuntimeConfig(
        provider="local",
        model="model-default",
        api_base="",
        api_key="",
        embedding_space_hash="space-default",
        collection_name="documents",
        dataset_scoped=False,
    )
    runtime_custom = DatasetEmbeddingRuntimeConfig(
        provider="local",
        model="model-custom",
        api_base="",
        api_key="",
        embedding_space_hash="space-custom",
        collection_name="documents_emb_space_custom",
        dataset_scoped=True,
    )
    global_calls: list[dict[str, object]] = []
    adapter_calls: list[dict[str, object]] = []

    vector_store = SimpleNamespace(
        search=lambda **kwargs: global_calls.append(dict(kwargs))
        or [
            {
                "chunk_id": "global-hit",
                "content": "global hit",
                "score": 0.8,
                "metadata": {"dataset_id": str(dataset_a), "embedding_space_hash": "space-default"},
            }
        ]
    )
    monkeypatch.setattr(
        HybridRetriever,
        "_resolve_dataset_runtime_shards",
        lambda self, *, tenant_id, dataset_ids=None: [  # noqa: ANN001,ARG005
            (runtime_default, (dataset_a,)),
            (runtime_custom, (dataset_b,)),
        ],
    )
    monkeypatch.setattr(HybridRetriever, "_resolve_embedding_runtime", lambda self, *, tenant_id: _embedding_runtime())
    monkeypatch.setattr(retriever_module, "get_vector_store", lambda: vector_store)
    monkeypatch.setattr(
        retriever_module,
        "create_embeddings_for_runtime",
        lambda runtime: SimpleNamespace(embed_query=lambda _query: [1.0]),
    )
    monkeypatch.setattr(retriever_module, "resolve_collection_name", lambda name: name)
    monkeypatch.setattr(
        retriever_module,
        "get_milvus_adapter",
        lambda name: SimpleNamespace(
            search=lambda **kwargs: adapter_calls.append({"collection": name, **dict(kwargs)})
            or [
                {
                    "chunk_id": "custom-hit",
                    "content": "custom hit",
                    "score": 0.7,
                    "metadata": {"dataset_id": str(dataset_b), "embedding_space_hash": "space-custom"},
                }
            ]
        ),
    )
    monkeypatch.setattr(HybridRetriever, "_search_bm25", lambda self, **kwargs: [])  # noqa: ANN001

    results = HybridRetriever(
        tenant_id=tenant_id,
        dataset_ids=[dataset_a, dataset_b],
        retrieval_mode="vector",
        enable_reranker=False,
        sparse_enabled=False,
        dedup_enabled=False,
    )._hybrid_search(
        "scope query",
        top_k=2,
        score_threshold=0.0,
        retrieval_mode="vector",
    )

    assert [item["content"] for item in results] == ["global hit", "custom hit"]
    assert global_calls and global_calls[0]["metadata_filter"] == {
        "dataset_id": str(dataset_a),
        "embedding_space_hash": {"$in": ["space-default", ""]},
    }
    assert global_calls[0]["tenant_id"] == tenant_id
    assert adapter_calls and adapter_calls[0]["collection"] == runtime_custom.collection_name
    assert adapter_calls[0]["metadata_filter"] == {
        "tenant_id": str(tenant_id),
        "dataset_id": str(dataset_b),
        "embedding_space_hash": {"$in": ["space-custom", ""]},
    }

def test_bm25_lru_eviction_keeps_cache_maps_aligned(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings
    from app.rag.retriever import HybridRetriever

    retriever = HybridRetriever(document_ids=[uuid.uuid4()])
    monkeypatch.setattr(settings, "BM25_CACHE_MAX_TENANTS", 2, raising=False)

    for key in ("scope-a", "scope-b", "scope-c"):
        retriever._bm25_retrievers[key] = object()  # type: ignore[assignment]
        retriever._bm25_docs[key] = []
        retriever._bm25_doc_ids[key] = set()
        retriever._chunk_id_lookup[key] = {}
        retriever._bm25_cache_versions[key] = key
        retriever._touch_bm25_cache(key)

    expected = {"scope-b", "scope-c"}
    assert set(retriever._bm25_cache_order) == expected
    assert set(retriever._bm25_retrievers) == expected
    assert set(retriever._bm25_docs) == expected
    assert set(retriever._bm25_doc_ids) == expected
    assert set(retriever._chunk_id_lookup) == expected
    assert set(retriever._bm25_cache_versions) == expected
    assert isinstance(retriever._bm25_cache_order, OrderedDict)
