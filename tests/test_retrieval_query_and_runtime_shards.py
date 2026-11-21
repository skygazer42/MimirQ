import threading
import uuid
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.infrastructure.config import settings
from app.services.datasets.embedding_config import DatasetEmbeddingRuntimeConfig


def _runtime(space: str) -> DatasetEmbeddingRuntimeConfig:
    return DatasetEmbeddingRuntimeConfig(
        provider="openai_compatible",
        model=f"model-{space}",
        api_base="",
        api_key="",
        embedding_space_hash=space,
        collection_name=f"documents_{space}",
        dataset_scoped=True,
    )


def _configure_hybrid_runtime(monkeypatch, *, tenant_id, shards, outcome):
    from app.rag.retrieval.corpus import CorpusSearchResult
    from app.rag.retrieval.recall import retriever, vector_search
    from app.rag.retrieval.recall.runtime_scope import ResolvedRetrievalScope, RetrievalScope

    dataset_ids = tuple(dataset for shard in shards for dataset in shard.dataset_ids)
    resolved = ResolvedRetrievalScope(
        RetrievalScope(tenant_id, "member-1", dataset_ids),
        dataset_ids,
        shards,
        shards[0].runtime,
        None,
        None,
        None,
        False,
    )
    for name, value in {
        "RETRIEVAL_CANDIDATE_SINGLEFLIGHT_ENABLED": False,
        "RETRIEVAL_CANDIDATE_CACHE_ENABLED": False,
        "SEMANTIC_CACHE_ENABLED": False,
        "BM25_INDEX_ENABLED": True,
        "VECTOR_BACKEND": "milvus",
        "LEXICAL_DB_ENABLED": False,
    }.items():
        monkeypatch.setattr(settings, name, value)
    monkeypatch.setattr(retriever.HybridRetriever, "_resolve_hybrid_runtime_scope", lambda self, **kwargs: resolved)
    corpus = SimpleNamespace(
        search=lambda *args, **kwargs: CorpusSearchResult([], {}),
        chunk_id_lookup=lambda scope, *, candidates: {},
    )
    monkeypatch.setattr(retriever, "get_corpus_index", lambda: corpus)
    monkeypatch.setattr(vector_search, "search_vectors", lambda *args, **kwargs: outcome)


@pytest.mark.parametrize(
    ("model_type", "extra"),
    [
        pytest.param("retrieve_preview", {}, id="retrieve-preview"),
        pytest.param("tree_search", {}, id="tree-search"),
        pytest.param("evidence_retrieve", {}, id="evidence-retrieve"),
        pytest.param("prompt_preview", {}, id="prompt-preview"),
        pytest.param("dify_retrieval", {"knowledge_id": "knowledge-1"}, id="dify-retrieval"),
        pytest.param("dify_conversation", {"answer": "answer"}, id="dify-conversation"),
        pytest.param("retrieval_explain", {}, id="retrieval-explain"),
    ],
)
def test_retrieval_query_models_share_configured_length_limit(model_type: str, extra: dict[str, object]) -> None:
    from app.api.v1.integrations import dify as integrations_dify
    from app.api.v1.retrieval import explain as retrieval_explain
    from app.api.v1.retrieval import routes as rag

    models = {
        "retrieve_preview": rag.RetrievePreviewRequest,
        "tree_search": rag.TreeSearchPreviewRequest,
        "evidence_retrieve": rag.EvidenceRetrieveRequest,
        "prompt_preview": rag.PromptPreviewRequest,
        "dify_retrieval": integrations_dify.DifyExternalKnowledgeRequest,
        "dify_conversation": integrations_dify.DifyConversationTurnRequest,
        "retrieval_explain": retrieval_explain.RetrievalExplainRequest,
    }
    model = models[model_type]
    limit = int(settings.RETRIEVAL_QUERY_MAX_CHARS)

    assert model(query="q" * limit, **extra).query == "q" * limit
    with pytest.raises(ValidationError):
        model(query="q" * (limit + 1), **extra)


@pytest.mark.parametrize("model_name", ["RetrievePreviewRequest", "EvidenceRetrieveRequest"])
def test_explicit_image_vector_queries_are_retired(model_name: str) -> None:
    from app.api.v1.retrieval import routes as rag

    model = getattr(rag, model_name)
    with pytest.raises(ValidationError, match="retired"):
        model(query="query", query_image="find image")


def test_chat_request_message_limit_is_exposed_and_enforced_by_http_schema() -> None:
    from app.api.schemas.conversations.chat import ChatRequest

    limit = int(settings.RETRIEVAL_QUERY_MAX_CHARS)
    app = FastAPI()

    @app.post("/chat")
    def chat(body: ChatRequest) -> dict[str, str]:
        return {"message": body.message}

    message_schema = app.openapi()["components"]["schemas"]["ChatRequest"]["properties"]["message"]
    assert message_schema["minLength"] == 1
    assert message_schema["maxLength"] == limit
    assert ChatRequest(message="m" * limit).message == "m" * limit

    response = TestClient(app).post("/chat", json={"message": "m" * (limit + 1)})
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "message"]


def test_external_history_role_rejects_system_but_internal_summary_dict_remains_supported() -> None:
    from app.api.schemas.conversations.chat import HistoryMessage
    from app.rag.llm.prompts.templates import format_history_text

    assert HistoryMessage(role="user", content="question").role == "user"
    assert HistoryMessage(role="assistant", content="answer").role == "assistant"
    with pytest.raises(ValidationError):
        HistoryMessage(role="system", content="untrusted instruction")

    assert format_history_text([{"role": "system", "content": "trusted summary"}], window=1) == (
        "System: trusted summary"
    )


def test_hybrid_retriever_rejects_oversized_query_before_retrieval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.rag.retrieval.recall.retriever import HybridRetriever

    monkeypatch.setattr(settings, "RETRIEVAL_QUERY_MAX_CHARS", 3)
    monkeypatch.setattr(
        HybridRetriever,
        "_hybrid_search_batch",
        lambda *_args, **_kwargs: pytest.fail("oversized query reached retrieval channels"),
    )

    with pytest.raises(ValueError, match=r"RETRIEVAL_QUERY_MAX_CHARS=3"):
        HybridRetriever().invoke("four")


def test_dataset_runtime_resolution_groups_identical_embedding_configs(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.rag.retrieval.recall import runtime_scope, vector_search

    monkeypatch.setattr(vector_search, "run_with_retrieval_backend_budget_sync", lambda call, *args: call(*args))
    tenant_id = uuid.uuid4()
    dataset_ids = (uuid.uuid4(), uuid.uuid4())
    metadata = {"embedding_defaults": {"provider": "openai_compatible", "model": "shared-model"}}

    class _Query:
        def filter(self, *_args, **_kwargs):
            return self

        def all(self):
            return [(dataset_id, metadata) for dataset_id in dataset_ids]

    session = SimpleNamespace(query=lambda *_args: _Query(), close=lambda: None)
    shards = runtime_scope.load_runtime_shards(session, tenant_id=tenant_id, dataset_ids=dataset_ids)
    assert len(shards) == 1
    assert set(shards[0].dataset_ids) == set(dataset_ids)
    embed_calls: list[str] = []
    embeddings = SimpleNamespace(embed_query=lambda query: embed_calls.append(query) or [1.0])
    adapter = SimpleNamespace(search=lambda **_kwargs: [])
    monkeypatch.setattr(vector_search, "create_embeddings_for_runtime", lambda _runtime: embeddings)
    monkeypatch.setattr(vector_search, "resolve_collection_name", lambda name: name)
    monkeypatch.setattr(vector_search, "get_milvus_adapter", lambda _name: adapter)
    vector_search.search_runtime_shards(
        vector_search.VectorSearchRequest(
            "query",
            1,
            0.0,
            runtime_scope.RetrievalScope(
                tenant_id=tenant_id, account_id="fixture", document_ids=(), metadata_filter=None
            ),
        ),
        shards=shards,
        vector_store=pytest.fail,
    )
    assert embed_calls == ["query"]


def test_multi_runtime_vector_search_uses_bounded_parallelism(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.rag.retrieval.recall import runtime_scope, vector_search

    monkeypatch.setattr(vector_search, "run_with_retrieval_backend_budget_sync", lambda call, *args: call(*args))
    monkeypatch.setattr(vector_search.settings, "RAG_VECTOR_SHARD_MAX_CONCURRENCY", 2, raising=False)
    monkeypatch.setattr(vector_search.settings, "RAG_VECTOR_SHARD_GLOBAL_MAX_CONCURRENCY", 2, raising=False)
    runtimes = [_runtime(f"space-{index}") for index in range(4)]
    shards = [(runtime, (uuid.uuid4(),)) for runtime in runtimes]
    lock = threading.Lock()
    rendezvous = threading.Barrier(2)
    active = 0
    max_active = 0
    thread_ids: set[int] = set()

    def search_shard(self, *, runtime, **_kwargs):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
            thread_ids.add(threading.get_ident())
        try:
            try:
                rendezvous.wait(timeout=0.3)
            except threading.BrokenBarrierError:
                pass
            return [{"content": runtime.embedding_space_hash, "score": 1.0, "metadata": {}}]
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(vector_search, "search_dataset_vectors", search_shard)
    batch = vector_search.search_runtime_shards(
        vector_search.VectorSearchRequest(
            "query",
            4,
            0.0,
            runtime_scope.RetrievalScope(
                tenant_id=uuid.uuid4(), account_id="fixture", document_ids=(), metadata_filter=None
            ),
        ),
        shards=tuple((runtime_scope.RuntimeShard(runtime, datasets) for runtime, datasets in shards)),
        vector_store=pytest.fail,
    )
    results, failures = (batch.records, batch.failures)
    assert failures == ()
    assert len(results) == 4
    assert max_active == 2
    assert len(thread_ids) == 2


def test_single_runtime_vector_search_stays_on_caller_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.rag.retrieval.recall import runtime_scope, vector_search

    monkeypatch.setattr(vector_search, "run_with_retrieval_backend_budget_sync", lambda call, *args: call(*args))
    caller_thread_id = threading.get_ident()
    search_thread_ids: list[int] = []

    class _UnexpectedExecutor:
        def __init__(self, *_args, **_kwargs):
            pytest.fail("single-shard search must not create a thread pool")

    def search_shard(self, **_kwargs):
        search_thread_ids.append(threading.get_ident())
        return [{"content": "single", "score": 1.0, "metadata": {}}]

    monkeypatch.setattr(vector_search, "ThreadPoolExecutor", _UnexpectedExecutor, raising=False)
    monkeypatch.setattr(vector_search, "search_dataset_vectors", search_shard)
    runtime = _runtime("single")
    batch = vector_search.search_runtime_shards(
        vector_search.VectorSearchRequest(
            "query",
            1,
            0.0,
            runtime_scope.RetrievalScope(
                tenant_id=uuid.uuid4(), account_id="fixture", document_ids=(), metadata_filter=None
            ),
        ),
        shards=tuple(
            (runtime_scope.RuntimeShard(runtime, datasets) for runtime, datasets in [(runtime, (uuid.uuid4(),))])
        ),
        vector_store=pytest.fail,
    )
    results, failures = (batch.records, batch.failures)
    assert failures == ()
    assert [item["content"] for item in results] == ["single"]
    assert search_thread_ids == [caller_thread_id]


def test_vector_runtime_shards_preserve_failure_degradation_and_global_top_k(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.rag.retrieval.recall import runtime_scope, vector_search

    monkeypatch.setattr(vector_search, "run_with_retrieval_backend_budget_sync", lambda call, *args: call(*args))
    monkeypatch.setattr(vector_search.settings, "RAG_VECTOR_SHARD_MAX_CONCURRENCY", 2, raising=False)
    runtimes = [_runtime("low"), _runtime("failed"), _runtime("high")]

    def search_shard(self, *, runtime, **_kwargs):
        if runtime.embedding_space_hash == "failed":
            raise RuntimeError("shard unavailable")
        score = 0.9 if runtime.embedding_space_hash == "high" else 0.4
        return [{"content": runtime.embedding_space_hash, "score": score, "metadata": {}}]

    monkeypatch.setattr(vector_search, "search_dataset_vectors", search_shard)
    batch = vector_search.search_runtime_shards(
        vector_search.VectorSearchRequest(
            "query",
            1,
            0.0,
            runtime_scope.RetrievalScope(
                tenant_id=uuid.uuid4(), account_id="fixture", document_ids=(), metadata_filter=None
            ),
        ),
        shards=tuple(
            (
                runtime_scope.RuntimeShard(runtime, datasets)
                for runtime, datasets in [(runtime, (uuid.uuid4(),)) for runtime in runtimes]
            )
        ),
        vector_store=pytest.fail,
    )
    results, failures = (batch.records, batch.failures)
    assert [item["content"] for item in results] == ["high"]
    assert results[0]["metadata"]["_retrieval_expected_embedding_space_hash"] == "high"
    assert len(failures) == 1
    assert str(failures[0]) == "shard unavailable"


def test_multi_runtime_vector_search_wraps_each_shard_with_backend_budget_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.rag.retrieval.recall import runtime_scope, vector_search

    monkeypatch.setattr(vector_search.settings, "RAG_VECTOR_SHARD_MAX_CONCURRENCY", 2, raising=False)
    runtimes = [_runtime(f"space-{index}") for index in range(3)]
    helper_calls: list[str] = []

    def _budget(func, *args, **kwargs):
        helper_calls.append(threading.current_thread().name)
        return func(*args, **kwargs)

    def search_shard(self, *, runtime, **_kwargs):
        return [{"content": runtime.embedding_space_hash, "score": 1.0, "metadata": {}}]

    monkeypatch.setattr(vector_search, "run_with_retrieval_backend_budget_sync", _budget, raising=True)
    monkeypatch.setattr(vector_search, "search_dataset_vectors", search_shard)
    batch = vector_search.search_runtime_shards(
        vector_search.VectorSearchRequest(
            "query",
            3,
            0.0,
            runtime_scope.RetrievalScope(
                tenant_id=uuid.uuid4(), account_id="fixture", document_ids=(), metadata_filter=None
            ),
        ),
        shards=tuple(
            (
                runtime_scope.RuntimeShard(runtime, datasets)
                for runtime, datasets in [(runtime, (uuid.uuid4(),)) for runtime in runtimes]
            )
        ),
        vector_store=pytest.fail,
    )
    results, failures = (batch.records, batch.failures)
    assert failures == ()
    assert len(results) == 3
    assert len(helper_calls) == 3


def test_vector_runtime_shards_are_deterministic_for_equal_scores(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.rag.retrieval.recall import runtime_scope, vector_search

    monkeypatch.setattr(vector_search, "run_with_retrieval_backend_budget_sync", lambda call, *args: call(*args))
    runtimes = [_runtime("space-b"), _runtime("space-a")]
    shard_hits = {
        "space-b": [
            {
                "chunk_id": "chunk-b",
                "content": "beta",
                "score": 0.9,
                "metadata": {"document_id": "doc-b", "chunk_index": 0, "chunk_id": "chunk-b"},
            }
        ],
        "space-a": [
            {
                "chunk_id": "chunk-a",
                "content": "alpha",
                "score": 0.9,
                "metadata": {"document_id": "doc-a", "chunk_index": 0, "chunk_id": "chunk-a"},
            }
        ],
    }

    def search_shard(self, *, runtime, **_kwargs):
        return shard_hits[runtime.embedding_space_hash]

    monkeypatch.setattr(vector_search, "search_dataset_vectors", search_shard)
    batch = vector_search.search_runtime_shards(
        vector_search.VectorSearchRequest(
            "query",
            2,
            0.0,
            runtime_scope.RetrievalScope(
                tenant_id=uuid.uuid4(), account_id="fixture", document_ids=(), metadata_filter=None
            ),
        ),
        shards=tuple(
            (
                runtime_scope.RuntimeShard(runtime, datasets)
                for runtime, datasets in [(runtime, (uuid.uuid4(),)) for runtime in runtimes]
            )
        ),
        vector_store=pytest.fail,
    )
    results, failures = (batch.records, batch.failures)
    assert failures == ()
    assert [item["chunk_id"] for item in results] == ["chunk-a", "chunk-b"]


def test_vector_runtime_shards_degrade_when_backend_budget_helper_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.rag.retrieval.recall import runtime_scope, vector_search
    from app.services.runtime.retrieval_limiter import RetrievalAdmissionTimeoutError

    runtimes = [_runtime("ok"), _runtime("timed-out")]

    def _budget(func, shard, *args, **kwargs):
        runtime = shard.runtime
        if runtime.embedding_space_hash == "timed-out":
            raise RetrievalAdmissionTimeoutError(0.2)
        return func(shard, *args, **kwargs)

    def search_shard(self, *, runtime, **_kwargs):
        return [{"content": runtime.embedding_space_hash, "score": 1.0, "metadata": {}}]

    monkeypatch.setattr(vector_search, "run_with_retrieval_backend_budget_sync", _budget, raising=True)
    monkeypatch.setattr(vector_search, "search_dataset_vectors", search_shard)
    batch = vector_search.search_runtime_shards(
        vector_search.VectorSearchRequest(
            "query",
            2,
            0.0,
            runtime_scope.RetrievalScope(
                tenant_id=uuid.uuid4(), account_id="fixture", document_ids=(), metadata_filter=None
            ),
        ),
        shards=tuple(
            (
                runtime_scope.RuntimeShard(runtime, datasets)
                for runtime, datasets in [(runtime, (uuid.uuid4(),)) for runtime in runtimes]
            )
        ),
        vector_store=pytest.fail,
    )
    results, failures = (batch.records, batch.failures)
    assert [item["content"] for item in results] == ["ok"]
    assert len(failures) == 1
    assert isinstance(failures[0], RetrievalAdmissionTimeoutError)


def test_hybrid_search_degrades_when_some_runtime_shards_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.rag.retrieval.recall import vector_search
    from app.rag.retrieval.recall.retriever import HybridRetriever
    from app.rag.retrieval.recall.runtime_scope import RuntimeShard
    from app.services.runtime.retrieval_limiter import RetrievalAdmissionTimeoutError

    tenant_id, dataset_id, failed_dataset = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    runtime = _runtime("test-space")
    shards = (RuntimeShard(runtime, (dataset_id,)), RuntimeShard(_runtime("timed-out"), (failed_dataset,)))
    records = vector_search.tag_expected_space(
        [
            {
                "chunk_id": "chunk-1",
                "content": "vector ok",
                "score": 0.9,
                "metadata": {
                    "document_id": "doc-1",
                    "dataset_id": str(dataset_id),
                    "chunk_id": "chunk-1",
                    "embedding_space_hash": runtime.embedding_space_hash,
                },
            }
        ],
        expected_space=runtime.embedding_space_hash,
    )
    outcome = vector_search.VectorSearchBatch(
        records,
        (
            vector_search.VectorShardResult(shards[0], records, None),
            vector_search.VectorShardResult(shards[1], [], RetrievalAdmissionTimeoutError(0.2)),
        ),
    )
    _configure_hybrid_runtime(monkeypatch, tenant_id=tenant_id, shards=shards, outcome=outcome)
    retriever = HybridRetriever(
        tenant_id=tenant_id,
        account_id="member-1",
        dataset_ids=[dataset_id, failed_dataset],
        retrieval_mode="hybrid",
        enable_reranker=False,
        dedup_enabled=False,
    )
    out = retriever._hybrid_search("query", top_k=1, score_threshold=0.0, tenant_id=tenant_id, retrieval_mode="hybrid")
    assert [item["content"] for item in out] == ["vector ok"]


def test_hybrid_search_propagates_retryable_timeout_when_all_runtime_shards_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.rag.retrieval.recall import vector_search
    from app.rag.retrieval.recall.retriever import HybridRetriever
    from app.rag.retrieval.recall.runtime_scope import RuntimeShard
    from app.services.runtime.retrieval_limiter import RetrievalAdmissionTimeoutError

    tenant_id, dataset_id = uuid.uuid4(), uuid.uuid4()
    shards = (RuntimeShard(_runtime("test-space"), (dataset_id,)),)
    outcome = vector_search.VectorSearchBatch(
        [], (vector_search.VectorShardResult(shards[0], [], RetrievalAdmissionTimeoutError(0.2)),)
    )
    _configure_hybrid_runtime(monkeypatch, tenant_id=tenant_id, shards=shards, outcome=outcome)
    retriever = HybridRetriever(
        tenant_id=tenant_id,
        account_id="member-1",
        dataset_id=dataset_id,
        retrieval_mode="hybrid",
        enable_reranker=False,
        dedup_enabled=False,
    )
    with pytest.raises(RetrievalAdmissionTimeoutError):
        retriever._hybrid_search("query", top_k=1, score_threshold=0.0, tenant_id=tenant_id, retrieval_mode="hybrid")
