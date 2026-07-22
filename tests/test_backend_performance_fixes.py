import asyncio
import sys
import threading
import uuid
from dataclasses import replace
from types import SimpleNamespace

import httpx
import pytest


def test_metadata_worker_reduces_budget_by_gate_queue_time(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.integrations_dify as dify_api

    worker_db = SimpleNamespace(close=lambda: None)
    observed_budgets: list[int] = []
    monkeypatch.setattr(dify_api, "SessionLocal", lambda: worker_db, raising=True)
    monkeypatch.setattr(dify_api.time, "perf_counter", lambda: 10.0, raising=True)

    def fake_fallback(**kwargs):  # noqa: ANN003, ANN202
        observed_budgets.append(kwargs["max_elapsed_ms"])
        return []

    monkeypatch.setattr(dify_api, "_metadata_anchor_db_fallback_records", fake_fallback, raising=True)

    result = dify_api._metadata_anchor_db_fallback_records_with_managed_session(
        budget_deadline=10.25,
        max_elapsed_ms=1000,
    )

    assert result == []
    assert observed_budgets == [250]


def test_metadata_worker_skips_session_when_gate_queue_exhausts_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    session_created = False

    def create_session():  # noqa: ANN202
        nonlocal session_created
        session_created = True
        return SimpleNamespace(close=lambda: None)

    monkeypatch.setattr(dify_api, "SessionLocal", create_session, raising=True)
    monkeypatch.setattr(dify_api.time, "perf_counter", lambda: 10.0, raising=True)

    result = dify_api._metadata_anchor_db_fallback_records_with_managed_session(
        budget_deadline=9.9,
        max_elapsed_ms=1000,
    )

    assert result == []
    assert session_created is False


def test_metadata_fallback_does_not_query_after_connection_wait_exhausts_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    query_called = False

    class _SlowCheckoutDB:
        def execute(self, _statement):  # noqa: ANN001, ANN202
            import time

            time.sleep(0.03)

        def query(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            nonlocal query_called
            query_called = True
            raise RuntimeError("query must not run after the budget expires")

        def rollback(self) -> None:
            return None

    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_METADATA_ANCHOR_DB_FALLBACK_ENABLED",
        True,
        raising=False,
    )

    result = dify_api._metadata_anchor_db_fallback_records(
        db=_SlowCheckoutDB(),
        tenant_id=uuid.uuid4(),
        dataset_ids=[uuid.uuid4()],
        query="generic service lookup",
        top_k=1,
        max_elapsed_ms=10,
    )

    assert result == []
    assert query_called is False


@pytest.mark.asyncio
async def test_dify_chunk_hydration_uses_worker_session_off_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    loop_thread_id = threading.get_ident()
    events: list[str] = []
    worker_db = SimpleNamespace(close=lambda: events.append("close"))
    request_db = SimpleNamespace(rollback=lambda: events.append("rollback"))
    observed: list[tuple[object, int]] = []
    monkeypatch.setattr(dify_api, "SessionLocal", lambda: worker_db, raising=True)
    monkeypatch.setattr(
        dify_api,
        "_load_chunk_content_map",
        lambda **kwargs: observed.append((kwargs["db"], threading.get_ident())) or {"chunk": "full"},
        raising=True,
    )

    result = await dify_api._offload_chunk_content_hydration(
        request_db=request_db,
        tenant_id=uuid.uuid4(),
        citations=[],
    )

    assert result == {"chunk": "full"}
    assert events == ["rollback", "close"]
    assert observed == [(worker_db, observed[0][1])]
    assert observed[0][1] != loop_thread_id


@pytest.mark.asyncio
async def test_dify_kg_hydration_uses_worker_session_off_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    loop_thread_id = threading.get_ident()
    events: list[str] = []
    worker_db = SimpleNamespace(close=lambda: events.append("close"))
    request_db = SimpleNamespace(rollback=lambda: events.append("rollback"))
    observed: list[tuple[object, int]] = []
    monkeypatch.setattr(dify_api, "SessionLocal", lambda: worker_db)
    monkeypatch.setattr(
        dify_api,
        "_load_dify_kg_chunk_rows",
        lambda **kwargs: observed.append((kwargs["db"], threading.get_ident())) or ["row"],
        raising=False,
    )

    rows = await dify_api._offload_dify_kg_chunk_rows(
        request_db=request_db,
        tenant_id=uuid.uuid4(),
        dataset_ids=[uuid.uuid4()],
        chunk_ids=[uuid.uuid4()],
    )

    assert rows == ["row"]
    assert events == ["rollback", "close"]
    assert observed[0][0] is worker_db
    assert observed[0][1] != loop_thread_id


@pytest.mark.asyncio
async def test_retrieval_limiter_drops_cancelled_queued_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.rag_runtime_limiter as limiter

    first_started = threading.Event()
    release_first = threading.Event()
    queued_work_ran = threading.Event()
    monkeypatch.setattr(limiter.settings, "RAG_RETRIEVAL_OFFLOAD_MAX_CONCURRENCY", 1)

    def first_work() -> str:
        first_started.set()
        assert release_first.wait(timeout=2)
        return "first"

    first_task = asyncio.create_task(limiter.run_blocking_retrieval_call(first_work))
    assert await asyncio.to_thread(first_started.wait, 1)

    queued_task = asyncio.create_task(
        limiter.run_blocking_retrieval_call(lambda: queued_work_ran.set())
    )
    await asyncio.sleep(0.05)
    queued_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await queued_task

    release_first.set()
    assert await first_task == "first"
    await asyncio.sleep(0.1)
    assert queued_work_ran.is_set() is False


def test_sync_retrieval_limiter_drops_cancellation_racing_with_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.rag_runtime_limiter as limiter

    cancel_event = threading.Event()
    work_ran = False

    class _CancellingGate:
        releases = 0

        def acquire(self, *, timeout: float) -> bool:  # noqa: ARG002
            cancel_event.set()
            return True

        def release(self) -> None:
            self.releases += 1

    gate = _CancellingGate()

    def work() -> None:
        nonlocal work_ran
        work_ran = True

    monkeypatch.setattr(limiter.settings, "RAG_RETRIEVAL_OFFLOAD_MAX_CONCURRENCY", 1)
    monkeypatch.setattr(limiter, "_get_gate", lambda _limit: gate)

    with pytest.raises(limiter.RetrievalAdmissionCancelledError):
        limiter.run_blocking_retrieval_call_sync(work, cancel_event=cancel_event)

    assert work_ran is False
    assert gate.releases == 1


@pytest.mark.asyncio
async def test_dify_final_reranker_shares_retrieval_admission_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api
    import app.services.rag_runtime_limiter as limiter
    from app.rag.reranker.types import RerankResult

    active = 0
    max_active = 0
    calls = 0
    lock = threading.Lock()
    first_started = threading.Event()
    release = threading.Event()

    class _BlockingReranker:
        def rerank(self, _query, candidates, **_kwargs):  # noqa: ANN001, ANN202
            nonlocal active, calls, max_active
            with lock:
                calls += 1
                active += 1
                max_active = max(max_active, active)
                first_started.set()
            try:
                assert release.wait(timeout=2)
                ordered_ids = [candidate.id for candidate in candidates]
                return RerankResult(
                    ordered_ids=ordered_ids,
                    score_map={candidate_id: 0.5 for candidate_id in ordered_ids},
                    provider="unit",
                )
            finally:
                with lock:
                    active -= 1

    monkeypatch.setattr(limiter.settings, "RAG_RETRIEVAL_OFFLOAD_MAX_CONCURRENCY", 1)
    monkeypatch.setattr(dify_api.settings, "ENABLE_RERANKER", True, raising=False)
    monkeypatch.setattr(
        dify_api.settings,
        "DIFY_EXTERNAL_KNOWLEDGE_RERANKER_ENABLED",
        True,
        raising=False,
    )
    monkeypatch.setattr(dify_api.settings, "RERANKER_PROVIDER", "unit", raising=False)
    monkeypatch.setattr(dify_api.settings, "RERANKER_TOP_N", 2, raising=False)
    monkeypatch.setattr(dify_api, "get_reranker", lambda _provider: _BlockingReranker())

    records = [
        {"content": "first", "score": 0.9, "title": "first.txt", "metadata": {}},
        {"content": "second", "score": 0.8, "title": "second.txt", "metadata": {}},
    ]
    tasks = [
        asyncio.create_task(
            dify_api._final_rerank_records_for_query(records, query=query, top_k=2)
        )
        for query in ("query one", "query two")
    ]
    try:
        assert await asyncio.to_thread(first_started.wait, 1)
        await asyncio.sleep(0.05)
        assert max_active == 1
    finally:
        release.set()
        await asyncio.gather(*tasks, return_exceptions=True)

    assert calls == 2


def test_dify_chunk_hydration_closes_worker_session_after_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.integrations_dify as dify_api

    closed = False

    class _WorkerDB:
        def close(self) -> None:
            nonlocal closed
            closed = True

    monkeypatch.setattr(dify_api, "SessionLocal", _WorkerDB, raising=True)
    monkeypatch.setattr(
        dify_api,
        "_load_chunk_content_map",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("hydrate failed")),
        raising=True,
    )

    with pytest.raises(RuntimeError, match="hydrate failed"):
        dify_api._load_chunk_content_map_with_managed_session(
            tenant_id=uuid.uuid4(),
            citations=[],
        )

    assert closed is True


@pytest.mark.asyncio
async def test_sync_iterator_worker_runs_source_off_event_loop() -> None:
    from app.services.chat_stream_graph import _iterate_sync_in_worker

    loop_thread_id = threading.get_ident()
    source_thread_ids: list[int] = []

    def source():
        source_thread_ids.append(threading.get_ident())
        yield "event"

    stream = _iterate_sync_in_worker(source)
    try:
        assert await anext(stream) == "event"
    finally:
        await stream.aclose()

    assert len(source_thread_ids) == 1
    assert source_thread_ids[0] != loop_thread_id


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

    loop_thread_id = threading.get_ident()
    retrieval_thread_ids: list[int] = []

    def blocking_get(self, query, *, run_manager):  # noqa: ANN001,ARG001
        retrieval_thread_ids.append(threading.get_ident())
        return []

    monkeypatch.setattr(HybridRetriever, "_get_relevant_documents", blocking_get)
    retriever = HybridRetriever(document_ids=[uuid.uuid4()])

    assert await retriever.ainvoke("q") == []
    assert len(retrieval_thread_ids) == 1
    assert retrieval_thread_ids[0] != loop_thread_id


@pytest.mark.asyncio
async def test_stream_extractive_fallback_runs_retrieval_off_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.chat_stream_orchestrator as orchestrator
    import app.services.rag_runtime_limiter as limiter

    loop_thread_id = threading.get_ident()
    fallback_thread_ids: list[int] = []
    request_rollbacks = 0
    worker_closed = 0
    worker_db = object()

    def rollback() -> None:
        nonlocal request_rollbacks
        request_rollbacks += 1

    def close_worker() -> None:
        nonlocal worker_closed
        worker_closed += 1

    monkeypatch.setattr(
        limiter,
        "SessionLocal",
        lambda: SimpleNamespace(close=close_worker, marker=worker_db),
    )
    effective_rag_config = SimpleNamespace(answer_mode="extractive", retrieval_mode="hybrid", use_graph=False)
    runtime = SimpleNamespace(
        effective_rag_config=effective_rag_config,
        dataset_id_used=None,
        dataset_rag_defaults_applied_fields=[],
        effective_prompt_template_id=None,
        effective_prompt_template_key=None,
        effective_prompt_ab_experiment_key=None,
        dataset_prompt_defaults_applied_fields=[],
        dataset_rag_config_template_defaults_applied_fields=[],
        rag_config_template_meta={},
        history_for_llm=[],
        cache_feature_enabled=False,
        cache_key=None,
        cache_skip_reason=None,
        cache_eligible=False,
        cache_hit=False,
        full_response="",
        citations_data=[],
        metrics_data={},
        structured_data=None,
    )
    monkeypatch.setattr(orchestrator, "prepare_stream_chat_runtime", lambda **_kwargs: runtime)

    def fallback(**kwargs):
        assert kwargs["db"].marker is worker_db
        fallback_thread_ids.append(threading.get_ident())
        return SimpleNamespace(content="fallback", citations=[], metrics={}, structured_data=None)

    async def materialized_events(**_kwargs):
        yield {"type": "done", "data": {}}

    monkeypatch.setattr(orchestrator, "execute_extractive_fallback_once", fallback)
    monkeypatch.setattr(orchestrator, "stream_materialized_chat_events", materialized_events)

    async def is_disconnected() -> bool:
        return False

    request = SimpleNamespace(
        message="question",
        enable_summary_memory=False,
        enable_structured_memory=False,
        structured_output=False,
        structured_preset=None,
    )
    events = [
        event
        async for event in orchestrator.stream_chat_sse_events(
            http_request=SimpleNamespace(
                state=SimpleNamespace(request_id="extractive-offload-test"),
                client=SimpleNamespace(host="127.0.0.1"),
                headers={},
                is_disconnected=is_disconnected,
            ),
            db=SimpleNamespace(rollback=rollback),
            tenant_id=uuid.uuid4(),
            account_id="member-1",
            request=request,
            conversation_id=None,
            scope_dataset_id=None,
            allowed_doc_ids=[],
            long_term_messages=[],
            assistant_message_id=uuid.uuid4(),
            tenant_qps_meta=None,
            quota_meta=None,
            spawn_background_task=lambda _task: None,
        )
    ]

    assert any('"type": "done"' in event for event in events)
    assert len(fallback_thread_ids) == 1
    assert fallback_thread_ids[0] != loop_thread_id
    assert request_rollbacks == 1
    assert worker_closed == 1


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


def test_weight_rerank_builds_document_frequency_without_repeated_list_scans(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.rag.retriever import HybridRetriever

    class CountingTokens(list[str]):
        contains_calls = 0

        def __contains__(self, item: object) -> bool:
            type(self).contains_calls += 1
            return super().__contains__(item)

    def tokenize(_self, text: str) -> list[str]:  # noqa: ANN001
        return CountingTokens(text.split())

    monkeypatch.setattr(HybridRetriever, "_bm25_tokenize", tokenize)
    documents = [
        {"chunk_id": "a", "content": "needle alpha alpha", "score": 0.4},
        {"chunk_id": "b", "content": "beta gamma", "score": 0.7},
        {"chunk_id": "c", "content": "delta epsilon", "score": 0.6},
    ]

    reranked = HybridRetriever()._weight_rerank(
        "needle",
        documents,
        vector_weight=0.6,
        keyword_weight=0.4,
    )

    assert [item["chunk_id"] for item in reranked] == ["b", "a", "c"]
    assert all("keyword_score" in item for item in reranked)
    assert all("keyword_score" not in item for item in documents)
    assert CountingTokens.contains_calls == 0


def test_plugin_retrieval_policy_scores_each_candidate_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.retrieval.plugin_policy as policy_module
    from app.rag.retriever import HybridRetriever

    calls = 0

    def score_policy(_policy, *, metadata_layers, query):  # noqa: ANN001,ANN202
        nonlocal calls
        calls += 1
        assert query == "target query"
        return policy_module.RetrievalPolicySignalScores(
            boost_field=float(metadata_layers[0]["policy_boost"]),
        )

    monkeypatch.setattr(policy_module, "retrieval_policy_signal_scores", score_policy)
    monkeypatch.setattr(
        HybridRetriever,
        "_retrieval_policy_for_plugin_ref",
        staticmethod(lambda _ref: {"schema": "mimirq.retrieval_policy.v1"}),
    )
    records = [
        {
            "chunk_id": f"chunk-{index}",
            "content": "unrelated content",
            "score": 0.5,
            "metadata": {
                "chunk_python_plugin": "plugin:test@1.0.0:chunk",
                "policy_boost": boost,
            },
        }
        for index, boost in enumerate((0.1, 0.3, 0.2))
    ]

    retriever = HybridRetriever()
    ranked = retriever._apply_plugin_retrieval_policy(records, query="target query")

    assert [item["chunk_id"] for item in ranked] == ["chunk-1", "chunk-2", "chunk-0"]
    assert calls == len(records)
    diagnostics = retriever._last_channel_metrics["retrieval_policy"]
    assert diagnostics["retrieval_policy_record_count"] == 3
    assert diagnostics["retrieval_policy_boosted_record_count"] == 3
    assert diagnostics["retrieval_policy_boost_field_record_count"] == 3
    assert diagnostics["max_bonus"] == pytest.approx(0.3)
    assert diagnostics["min_bonus"] == pytest.approx(0.1)
    assert diagnostics["avg_bonus"] == pytest.approx(0.2)
