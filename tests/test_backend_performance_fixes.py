import asyncio
import sys
import threading
import time
import uuid
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest


@pytest.mark.asyncio
async def test_sync_iterator_worker_keeps_event_loop_responsive() -> None:
    from app.services.chat_stream_graph import _iterate_sync_in_worker

    release = threading.Event()

    def source():
        release.wait(0.25)
        yield "event"

    stream = _iterate_sync_in_worker(source)
    timer = threading.Timer(0.25, release.set)
    timer.start()
    started = time.monotonic()
    pending = asyncio.create_task(anext(stream))
    try:
        await asyncio.sleep(0.02)
        elapsed = time.monotonic() - started
        release.set()
        assert await pending == "event"
        assert elapsed < 0.15
    finally:
        timer.cancel()
        release.set()
        await stream.aclose()


@pytest.mark.asyncio
async def test_sync_iterator_worker_propagates_errors() -> None:
    from app.services.chat_stream_graph import _iterate_sync_in_worker

    def source():
        yield "event"
        raise RuntimeError("graph failed")

    stream = _iterate_sync_in_worker(source)
    assert await anext(stream) == "event"
    with pytest.raises(RuntimeError, match="graph failed"):
        await anext(stream)


@pytest.mark.asyncio
async def test_sync_iterator_worker_bounds_buffer_and_closes_producer() -> None:
    from app.services.chat_stream_graph import _iterate_sync_in_worker

    closed = threading.Event()
    produced = 0

    def source():
        nonlocal produced
        try:
            for item in range(100):
                produced += 1
                yield item
        finally:
            closed.set()

    stream = _iterate_sync_in_worker(source, max_queue_size=2)
    assert await anext(stream) == 0
    await asyncio.sleep(0.05)
    assert produced <= 4
    await stream.aclose()
    assert await asyncio.to_thread(closed.wait, 0.5)


@pytest.mark.asyncio
async def test_async_retriever_does_not_run_sync_retrieval_on_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.rag.retriever import HybridRetriever

    release = threading.Event()

    def blocking_get(self, query, *, run_manager):  # noqa: ANN001,ARG001
        release.wait(0.25)
        return []

    monkeypatch.setattr(HybridRetriever, "_get_relevant_documents", blocking_get)
    retriever = HybridRetriever(document_ids=[uuid.uuid4()])
    timer = threading.Timer(0.25, release.set)
    timer.start()
    started = time.monotonic()
    pending = asyncio.create_task(retriever.ainvoke("q"))
    try:
        await asyncio.sleep(0.02)
        elapsed = time.monotonic() - started
        release.set()
        assert await pending == []
        assert elapsed < 0.15
    finally:
        timer.cancel()
        release.set()


@pytest.mark.parametrize(("replace_candidate", "expected_enrich_calls"), [(False, 1), (True, 2)])
def test_retriever_resolves_runtime_once_and_rechecks_only_new_candidate_identities(
    monkeypatch: pytest.MonkeyPatch,
    replace_candidate: bool,
    expected_enrich_calls: int,
) -> None:
    from app.core.config import settings
    from app.rag.retriever import HybridRetriever
    from app.services.dataset_embedding_config import DatasetEmbeddingRuntimeConfig

    tenant_id = uuid.uuid4()
    document_id = uuid.uuid4()
    child = {
        "chunk_id": str(uuid.uuid4()),
        "content": "child",
        "score": 1.0,
        "metadata": {"document_id": str(document_id), "chunk_index": 0},
    }
    parent = {
        "chunk_id": str(uuid.uuid4()),
        "content": "parent",
        "score": 1.0,
        "metadata": {"document_id": str(document_id), "chunk_index": 1},
    }
    runtime = DatasetEmbeddingRuntimeConfig(
        provider="local",
        model="model",
        api_base="",
        api_key="",
        embedding_space_hash="space",
        collection_name="documents_emb_space",
        dataset_scoped=True,
    )
    resolve_calls = 0
    enrich_calls = 0
    received_runtimes: list[DatasetEmbeddingRuntimeConfig | None] = []

    def resolve_runtime(self, *, tenant_id):  # noqa: ANN001,ARG001
        nonlocal resolve_calls
        resolve_calls += 1
        return runtime

    def hybrid_search(self, query, *, embedding_runtime=None, **kwargs):  # noqa: ANN001,ARG001
        received_runtimes.append(embedding_runtime)
        return [dict(child)]

    def enrich(self, results, *, embedding_runtime=None, **kwargs):  # noqa: ANN001,ARG001
        nonlocal enrich_calls
        enrich_calls += 1
        received_runtimes.append(embedding_runtime)
        return list(results)

    monkeypatch.setattr(settings, "RAG_CONTEXT_STITCHING_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_GOVERNANCE_PREFER_AUTHORITY", False, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_GOVERNANCE_PREFER_LATEST", False, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_GOVERNANCE_FILTER_SUPERSEDED", False, raising=False)
    monkeypatch.setattr(HybridRetriever, "_resolve_embedding_runtime", resolve_runtime)
    monkeypatch.setattr(HybridRetriever, "_hybrid_search", hybrid_search)
    monkeypatch.setattr(HybridRetriever, "_enrich_results_with_db_metadata", enrich)
    monkeypatch.setattr(HybridRetriever, "_expand_results_with_neighbors", lambda self, results: list(results))
    monkeypatch.setattr(
        HybridRetriever,
        "_auto_merge_parent_child",
        lambda self, results: [dict(parent)] if replace_candidate else list(results),
    )

    retriever = HybridRetriever(tenant_id=tenant_id, document_ids=[document_id], k=2)
    docs = retriever.invoke("q")

    assert [doc.page_content for doc in docs] == (["parent"] if replace_candidate else ["child"])
    assert resolve_calls == 1
    assert enrich_calls == expected_enrich_calls
    assert received_runtimes and all(item is runtime for item in received_runtimes)


def test_runtime_document_metadata_never_reads_source_pdf(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:  # noqa: ANN001
    from app.services.document_runtime_metadata import build_runtime_document_metadata

    source = tmp_path / "legacy.pdf"
    source.write_bytes(b"not-a-real-pdf")
    reader_calls = 0

    def fake_reader(_path):  # noqa: ANN001
        nonlocal reader_calls
        reader_calls += 1
        return SimpleNamespace(pages=[object(), object()])

    monkeypatch.setitem(sys.modules, "pypdf", SimpleNamespace(PdfReader=fake_reader))
    document = SimpleNamespace(file_type="pdf", file_path=str(source), doc_metadata={})

    assert build_runtime_document_metadata(document).get("page_count") is None
    assert reader_calls == 0


def test_dataset_embedding_runtime_reuses_bounded_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services.dataset_embedding_config as config_module

    calls: list[dict] = []

    def factory(**kwargs):  # noqa: ANN003
        calls.append(dict(kwargs))
        return object()

    runtime = config_module.DatasetEmbeddingRuntimeConfig(
        provider="local",
        model="model-a",
        api_base="",
        api_key="",
        embedding_space_hash="space-a",
        collection_name="documents_emb_space_a",
        dataset_scoped=True,
    )
    monkeypatch.setattr(config_module, "create_langchain_embeddings_from_config", factory)
    config_module.create_embeddings_for_runtime.cache_clear()
    try:
        first = config_module.create_embeddings_for_runtime(runtime)
        second = config_module.create_embeddings_for_runtime(runtime)
        third = config_module.create_embeddings_for_runtime(replace(runtime, model="model-b"))
    finally:
        config_module.create_embeddings_for_runtime.cache_clear()

    assert first is second
    assert third is not first
    assert len(calls) == 2
    assert config_module.create_embeddings_for_runtime.cache_info().maxsize == 8


@pytest.mark.asyncio
async def test_dashscope_embedding_reuses_shared_sync_and_async_clients(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.embedding.providers.dashscope as dashscope_module

    class SyncClient:
        def __init__(self) -> None:
            self.calls = 0

        def post(self, url, **kwargs):  # noqa: ANN001,ANN003
            self.calls += 1
            return httpx.Response(
                200,
                json={"code": "Success", "output": {"embeddings": [{"embedding": [3.0, 4.0]}]}},
                request=httpx.Request("POST", url),
            )

    class AsyncClient:
        def __init__(self) -> None:
            self.calls = 0

        async def post(self, url, **kwargs):  # noqa: ANN001,ANN003
            self.calls += 1
            return httpx.Response(
                200,
                json={"code": "Success", "output": {"embeddings": [{"embedding": [0.0, 2.0]}]}},
                request=httpx.Request("POST", url),
            )

    sync_client = SyncClient()
    async_client = AsyncClient()
    pool = SimpleNamespace(
        get_external_sync_client=lambda: sync_client,
        get_external_async_client=lambda: async_client,
    )
    monkeypatch.setattr(dashscope_module, "get_http_client_pool", lambda: pool)

    embedding = dashscope_module.DashScopeEmbedding(
        model="text-embedding-v4",
        api_key="test-key",
        base_url="https://dashscope.example/embeddings",
    )

    assert embedding.encode("sync")[0] == pytest.approx([0.6, 0.8])
    assert (await embedding.aencode("async"))[0] == pytest.approx([0.0, 1.0])
    assert sync_client.calls == 1
    assert async_client.calls == 1
