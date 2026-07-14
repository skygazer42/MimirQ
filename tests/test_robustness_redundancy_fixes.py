import asyncio
import threading
import time
import uuid
from collections import OrderedDict
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
                dataset_id=dataset_id,
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
