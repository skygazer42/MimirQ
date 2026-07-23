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


@pytest.mark.parametrize("retrieval_mode", ["vector", "keyword"])
@pytest.mark.parametrize("scope_kind", ["dataset_ids", "document_ids"])
def test_multi_runtime_dataset_scope_fans_out_vector_search_and_disables_cache(
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
    monkeypatch.setattr(retriever_module, "create_embeddings_for_runtime", lambda runtime: _Embeddings(runtime))
    monkeypatch.setattr(retriever_module, "resolve_collection_name", lambda name: name)
    monkeypatch.setattr(
        retriever_module,
        "get_milvus_adapter",
        lambda name: _Adapter(runtime_a if name == runtime_a.collection_name else runtime_b),
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
    assert cache_lookups == []
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
    assert retriever._last_channel_metrics["cache"]["skip_reason"] == "multi_runtime_scope"
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
    results = retriever._hybrid_search(
        "scope query",
        top_k=1,
        score_threshold=0.0,
        document_ids=[document_id],
        tenant_id=tenant_id,
        retrieval_mode="hybrid",
    )

    assert results == []
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

    assert behavior1 != behavior2
    assert behavior1 != behavior3

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
    document_rows = [
        (document_a, "a.md", dataset_a, "completed", {}, None, None, "published", 0, None, None, None),
        (document_b, "b.md", dataset_b, "completed", {}, None, None, "published", 0, None, None, None),
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
                [chunk_a, chunk_b],
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
        ],
        stats=stats,
        embedding_runtime=_embedding_runtime(),
    )

    assert [item["metadata"]["document_id"] for item in enriched] == [str(document_a), str(document_b)]
    assert enriched[0]["content"] == "chunk-a"
    assert enriched[1]["content"] == "chunk-b"
    assert stats["filtered_embedding_space"] == 1
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
    shards = HybridRetriever(dataset_ids=[dataset_a, dataset_b])._resolve_dataset_runtime_shards(
        tenant_id=tenant_id,
    )

    assert len(shards) == 1
    assert shards[0][1] == (dataset_a,)

    global_called = False
    cache_lookups: list[str] = []

    def global_search(**kwargs):  # noqa: ANN003
        nonlocal global_called
        global_called = True
        return []

    monkeypatch.setattr(retriever_module, "get_vector_store", lambda: SimpleNamespace(search=global_search))
    monkeypatch.setattr(
        retriever_module,
        "get_cached_retrieval_candidates",
        lambda key: cache_lookups.append(key) or [{"content": "stale cached hit", "score": 1.0}],
    )
    monkeypatch.setattr(HybridRetriever, "_resolve_embedding_runtime", lambda self, *, tenant_id: _embedding_runtime())
    monkeypatch.setattr(HybridRetriever, "_search_bm25", lambda self, **kwargs: [])  # noqa: ANN001
    monkeypatch.setattr(HybridRetriever, "_search_lexical_db", lambda self, **kwargs: [])  # noqa: ANN001

    retriever = HybridRetriever(
        tenant_id=tenant_id,
        account_id="member-1",
        dataset_ids=[dataset_b],
        retrieval_mode="vector",
        enable_reranker=False,
        sparse_enabled=False,
        dedup_enabled=False,
    )
    results = retriever._hybrid_search(
        "scope query",
        top_k=1,
        score_threshold=0.0,
        tenant_id=tenant_id,
        retrieval_mode="vector",
    )

    assert results == []
    assert global_called is False
    assert cache_lookups == []
    assert retriever._last_channel_metrics["cache"]["skip_reason"] == "missing_dataset_runtime"
    assert retriever._last_channel_metrics["cache"]["semantic"]["skip_reason"] == "missing_dataset_runtime"
    assert retriever._last_channel_metrics["retrieval_degraded"] is True


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
