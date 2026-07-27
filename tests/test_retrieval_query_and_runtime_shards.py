import threading
import uuid
from pathlib import Path
from runpy import run_path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import settings
from app.services.dataset_embedding_config import DatasetEmbeddingRuntimeConfig


def _runtime(space: str) -> DatasetEmbeddingRuntimeConfig:
    return DatasetEmbeddingRuntimeConfig(
        provider="local",
        model=f"model-{space}",
        api_base="",
        api_key="",
        embedding_space_hash=space,
        collection_name=f"documents_{space}",
        dataset_scoped=True,
    )


@pytest.mark.parametrize(
    ("model_type", "extra"),
    [
        pytest.param("retrieve_preview", {}, id="retrieve-preview"),
        pytest.param("tree_search", {}, id="tree-search"),
        pytest.param("image_search", {"dataset_id": uuid.uuid4()}, id="image-search"),
        pytest.param("evidence_retrieve", {}, id="evidence-retrieve"),
        pytest.param("prompt_preview", {}, id="prompt-preview"),
        pytest.param("dify_retrieval", {"knowledge_id": "knowledge-1"}, id="dify-retrieval"),
        pytest.param("dify_conversation", {"answer": "answer"}, id="dify-conversation"),
        pytest.param("retrieval_explain", {}, id="retrieval-explain"),
    ],
)
def test_retrieval_query_models_share_configured_length_limit(model_type: str, extra: dict[str, object]) -> None:
    from app.api.v1 import integrations_dify, rag, retrieval_explain

    models = {
        "retrieve_preview": rag.RetrievePreviewRequest,
        "tree_search": rag.TreeSearchPreviewRequest,
        "image_search": rag.ImageSearchRequest,
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
def test_explicit_image_queries_share_retrieval_query_length_limit(model_name: str) -> None:
    from app.api.v1 import rag

    model = getattr(rag, model_name)
    limit = int(settings.RETRIEVAL_QUERY_MAX_CHARS)

    assert model(query="query", query_image="i" * limit).query_image == "i" * limit
    with pytest.raises(ValidationError):
        model(query="query", query_image="i" * (limit + 1))


def test_chat_image_context_rejects_oversized_internal_query(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.chat_image_service import build_chat_image_context_docs

    monkeypatch.setattr(settings, "IMAGE_EMBEDDING_ENABLED", True)
    monkeypatch.setattr(settings, "RETRIEVAL_QUERY_MAX_CHARS", 3)

    with pytest.raises(ValueError, match=r"RETRIEVAL_QUERY_MAX_CHARS=3"):
        build_chat_image_context_docs(
            object(),  # type: ignore[arg-type]
            tenant_id=uuid.uuid4(),
            account_id="account-1",
            dataset_id=uuid.uuid4(),
            question="four",
        )


def test_chat_request_message_limit_is_exposed_and_enforced_by_http_schema() -> None:
    from app.api.schemas.chat import ChatRequest

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
    from app.api.schemas.chat import HistoryMessage
    from app.rag.core.conversation import format_history_text

    assert HistoryMessage(role="user", content="question").role == "user"
    assert HistoryMessage(role="assistant", content="answer").role == "assistant"
    with pytest.raises(ValidationError):
        HistoryMessage(role="system", content="untrusted instruction")

    assert format_history_text([{"role": "system", "content": "trusted summary"}], window=1) == (
        "System: trusted summary"
    )


def test_legacy_retrieval_tool_schema_enforces_query_limit() -> None:
    module = run_path(str(Path(__file__).parents[1] / "app" / "rag" / "tools.py"))
    retrieval_input = module["RetrievalInput"]
    limit = int(settings.RETRIEVAL_QUERY_MAX_CHARS)

    assert retrieval_input(query="q" * limit).query == "q" * limit
    with pytest.raises(ValidationError):
        retrieval_input(query="q" * (limit + 1))


def test_hybrid_retriever_rejects_oversized_query_before_retrieval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.rag.retriever import HybridRetriever

    monkeypatch.setattr(settings, "RETRIEVAL_QUERY_MAX_CHARS", 3)
    monkeypatch.setattr(
        HybridRetriever,
        "_hybrid_search",
        lambda *_args, **_kwargs: pytest.fail("oversized query reached retrieval channels"),
    )

    with pytest.raises(ValueError, match=r"RETRIEVAL_QUERY_MAX_CHARS=3"):
        HybridRetriever().invoke("four")


def test_dataset_runtime_resolution_groups_identical_embedding_configs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.retriever as retriever_module
    from app.rag.retriever import HybridRetriever

    tenant_id = uuid.uuid4()
    dataset_ids = (uuid.uuid4(), uuid.uuid4())
    metadata = {"embedding_defaults": {"provider": "local", "model": "shared-model"}}

    class _Query:
        def filter(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
            return self

        def all(self):  # noqa: ANN202
            return [(dataset_id, metadata) for dataset_id in dataset_ids]

    session = SimpleNamespace(query=lambda *_args: _Query(), close=lambda: None)
    monkeypatch.setattr(retriever_module, "SessionLocal", lambda: session)

    shards = HybridRetriever(dataset_ids=list(dataset_ids))._resolve_dataset_runtime_shards(tenant_id=tenant_id)

    assert len(shards) == 1
    assert set(shards[0][1]) == set(dataset_ids)

    embed_calls: list[str] = []
    embeddings = SimpleNamespace(embed_query=lambda query: embed_calls.append(query) or [1.0])
    adapter = SimpleNamespace(search=lambda **_kwargs: [])
    monkeypatch.setattr(retriever_module, "create_embeddings_for_runtime", lambda _runtime: embeddings)
    monkeypatch.setattr(retriever_module, "resolve_collection_name", lambda name: name)
    monkeypatch.setattr(retriever_module, "get_milvus_adapter", lambda _name: adapter)

    HybridRetriever()._search_vector_runtime_shards(
        query="query",
        top_k=1,
        score_threshold=0.0,
        document_ids=None,
        tenant_id=tenant_id,
        metadata_filter=None,
        runtime_shards=shards,
        vector_store=pytest.fail,
    )

    assert embed_calls == ["query"]


def test_multi_runtime_vector_search_uses_bounded_parallelism(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.retriever as retriever_module
    from app.rag.retriever import HybridRetriever

    monkeypatch.setattr(retriever_module.settings, "RAG_VECTOR_SHARD_MAX_CONCURRENCY", 2, raising=False)
    monkeypatch.setattr(
        retriever_module.settings,
        "RAG_VECTOR_SHARD_GLOBAL_MAX_CONCURRENCY",
        2,
        raising=False,
    )
    runtimes = [_runtime(f"space-{index}") for index in range(4)]
    shards = [(runtime, (uuid.uuid4(),)) for runtime in runtimes]
    lock = threading.Lock()
    rendezvous = threading.Barrier(2)
    active = 0
    max_active = 0
    thread_ids: set[int] = set()

    def search_shard(self, *, embedding_runtime, **_kwargs):  # noqa: ANN001, ANN003
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
            return [
                {
                    "content": embedding_runtime.embedding_space_hash,
                    "score": 1.0,
                    "metadata": {},
                }
            ]
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(HybridRetriever, "_search_dataset_scoped_vectors", search_shard)

    results, failures = HybridRetriever()._search_vector_runtime_shards(
        query="query",
        top_k=4,
        score_threshold=0.0,
        document_ids=None,
        tenant_id=uuid.uuid4(),
        metadata_filter=None,
        runtime_shards=shards,
        vector_store=pytest.fail,
    )

    assert failures == []
    assert len(results) == 4
    assert max_active == 2
    assert len(thread_ids) == 2


def test_single_runtime_vector_search_stays_on_caller_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.retriever as retriever_module
    from app.rag.retriever import HybridRetriever

    caller_thread_id = threading.get_ident()
    search_thread_ids: list[int] = []

    class _UnexpectedExecutor:
        def __init__(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
            pytest.fail("single-shard search must not create a thread pool")

    def search_shard(self, **_kwargs):  # noqa: ANN001, ANN003
        search_thread_ids.append(threading.get_ident())
        return [{"content": "single", "score": 1.0, "metadata": {}}]

    monkeypatch.setattr(retriever_module, "ThreadPoolExecutor", _UnexpectedExecutor, raising=False)
    monkeypatch.setattr(HybridRetriever, "_search_dataset_scoped_vectors", search_shard)
    runtime = _runtime("single")

    results, failures = HybridRetriever()._search_vector_runtime_shards(
        query="query",
        top_k=1,
        score_threshold=0.0,
        document_ids=None,
        tenant_id=uuid.uuid4(),
        metadata_filter=None,
        runtime_shards=[(runtime, (uuid.uuid4(),))],
        vector_store=pytest.fail,
    )

    assert failures == []
    assert [item["content"] for item in results] == ["single"]
    assert search_thread_ids == [caller_thread_id]


def test_vector_runtime_shards_preserve_failure_degradation_and_global_top_k(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.retriever as retriever_module
    from app.rag.retriever import HybridRetriever

    monkeypatch.setattr(retriever_module.settings, "RAG_VECTOR_SHARD_MAX_CONCURRENCY", 2, raising=False)
    runtimes = [_runtime("low"), _runtime("failed"), _runtime("high")]

    def search_shard(self, *, embedding_runtime, **_kwargs):  # noqa: ANN001, ANN003
        if embedding_runtime.embedding_space_hash == "failed":
            raise RuntimeError("shard unavailable")
        score = 0.9 if embedding_runtime.embedding_space_hash == "high" else 0.4
        return [{"content": embedding_runtime.embedding_space_hash, "score": score, "metadata": {}}]

    monkeypatch.setattr(HybridRetriever, "_search_dataset_scoped_vectors", search_shard)

    results, failures = HybridRetriever()._search_vector_runtime_shards(
        query="query",
        top_k=1,
        score_threshold=0.0,
        document_ids=None,
        tenant_id=uuid.uuid4(),
        metadata_filter=None,
        runtime_shards=[(runtime, (uuid.uuid4(),)) for runtime in runtimes],
        vector_store=pytest.fail,
    )

    assert [item["content"] for item in results] == ["high"]
    assert results[0]["metadata"]["_retrieval_expected_embedding_space_hash"] == "high"
    assert len(failures) == 1
    assert str(failures[0]) == "shard unavailable"


def test_multi_runtime_vector_search_wraps_each_shard_with_backend_budget_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.retriever as retriever_module
    from app.rag.retriever import HybridRetriever

    monkeypatch.setattr(retriever_module.settings, "RAG_VECTOR_SHARD_MAX_CONCURRENCY", 2, raising=False)
    runtimes = [_runtime(f"space-{index}") for index in range(3)]
    helper_calls: list[str] = []

    def _budget(func, *args, **kwargs):  # noqa: ANN001,ANN202
        helper_calls.append(threading.current_thread().name)
        return func(*args, **kwargs)

    def search_shard(self, *, embedding_runtime, **_kwargs):  # noqa: ANN001, ANN003
        return [{"content": embedding_runtime.embedding_space_hash, "score": 1.0, "metadata": {}}]

    monkeypatch.setattr(retriever_module, "run_with_retrieval_backend_budget_sync", _budget, raising=True)
    monkeypatch.setattr(HybridRetriever, "_search_dataset_scoped_vectors", search_shard)

    results, failures = HybridRetriever()._search_vector_runtime_shards(
        query="query",
        top_k=3,
        score_threshold=0.0,
        document_ids=None,
        tenant_id=uuid.uuid4(),
        metadata_filter=None,
        runtime_shards=[(runtime, (uuid.uuid4(),)) for runtime in runtimes],
        vector_store=pytest.fail,
    )

    assert failures == []
    assert len(results) == 3
    assert len(helper_calls) == 3


def test_vector_runtime_shards_degrade_when_backend_budget_helper_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.retriever as retriever_module
    from app.rag.retriever import HybridRetriever
    from app.services.rag_runtime_limiter import RetrievalAdmissionTimeoutError

    runtimes = [_runtime("ok"), _runtime("timed-out")]

    def _budget(func, shard, *args, **kwargs):  # noqa: ANN001,ANN202
        runtime, _dataset_ids = shard
        if runtime.embedding_space_hash == "timed-out":
            raise RetrievalAdmissionTimeoutError(0.2)
        return func(shard, *args, **kwargs)

    def search_shard(self, *, embedding_runtime, **_kwargs):  # noqa: ANN001, ANN003
        return [{"content": embedding_runtime.embedding_space_hash, "score": 1.0, "metadata": {}}]

    monkeypatch.setattr(retriever_module, "run_with_retrieval_backend_budget_sync", _budget, raising=True)
    monkeypatch.setattr(HybridRetriever, "_search_dataset_scoped_vectors", search_shard)

    results, failures = HybridRetriever()._search_vector_runtime_shards(
        query="query",
        top_k=2,
        score_threshold=0.0,
        document_ids=None,
        tenant_id=uuid.uuid4(),
        metadata_filter=None,
        runtime_shards=[(runtime, (uuid.uuid4(),)) for runtime in runtimes],
        vector_store=pytest.fail,
    )

    assert [item["content"] for item in results] == ["ok"]
    assert len(failures) == 1
    assert isinstance(failures[0], RetrievalAdmissionTimeoutError)


def test_hybrid_search_degrades_when_some_runtime_shards_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.retriever as retriever_module
    from app.rag.retriever import HybridRetriever
    from app.services.rag_runtime_limiter import RetrievalAdmissionTimeoutError

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    runtime = _runtime("test-space")

    for name, value in {
        "RETRIEVAL_CANDIDATE_SINGLEFLIGHT_ENABLED": False,
        "RETRIEVAL_CANDIDATE_CACHE_ENABLED": False,
        "SEMANTIC_CACHE_ENABLED": False,
    }.items():
        monkeypatch.setattr(retriever_module.settings, name, value, raising=False)

    monkeypatch.setattr(HybridRetriever, "_explicit_dataset_scope_ids", lambda self: (dataset_id,), raising=True)  # noqa: ANN001
    monkeypatch.setattr(HybridRetriever, "_resolve_dataset_runtime_shards", lambda self, *, tenant_id, dataset_ids=None: [(runtime, (dataset_id,))], raising=True)  # noqa: ANN001,ARG005,E501
    monkeypatch.setattr(HybridRetriever, "_resolve_embedding_runtime", lambda self, *, tenant_id: runtime, raising=True)  # noqa: ANN001,ARG005
    monkeypatch.setattr(HybridRetriever, "_search_vector_runtime_shards", lambda self, **kwargs: ([{"chunk_id": "chunk-1", "content": "vector ok", "score": 0.9, "metadata": {"document_id": "doc-1", "dataset_id": str(dataset_id), "chunk_id": "chunk-1", "embedding_space_hash": runtime.embedding_space_hash}}], [RetrievalAdmissionTimeoutError(0.2)]), raising=True)  # noqa: ANN001,E501
    monkeypatch.setattr(HybridRetriever, "_enrich_results_with_db_metadata", lambda self, items, **kwargs: list(items), raising=True)  # noqa: ANN001,ARG005
    monkeypatch.setattr(HybridRetriever, "_expand_results_with_neighbors", lambda self, items: list(items), raising=True)  # noqa: ANN001
    monkeypatch.setattr(HybridRetriever, "_auto_merge_parent_child", lambda self, items: list(items), raising=True)  # noqa: ANN001
    monkeypatch.setattr(HybridRetriever, "_deduplicate_results", lambda self, items: list(items), raising=True)  # noqa: ANN001
    monkeypatch.setattr(HybridRetriever, "_apply_document_diversity", lambda self, items, **kwargs: list(items), raising=True)  # noqa: ANN001,ARG005
    monkeypatch.setattr(HybridRetriever, "_apply_metadata_exact_anchor_post_ordering", lambda self, query, items, **kwargs: list(items), raising=True)  # noqa: ANN001,ARG005
    monkeypatch.setattr(HybridRetriever, "_merge_results", lambda self, vector_results, *args, **kwargs: list(vector_results), raising=True)  # noqa: ANN001,ARG005
    monkeypatch.setattr(HybridRetriever, "_search_bm25", lambda self, **kwargs: [], raising=True)  # noqa: ANN001,ARG005
    monkeypatch.setattr(HybridRetriever, "_search_lexical_db", lambda self, **kwargs: [], raising=True)  # noqa: ANN001,ARG005
    monkeypatch.setattr(HybridRetriever, "_search_sparse", lambda self, **kwargs: [], raising=True)  # noqa: ANN001,ARG005
    monkeypatch.setattr(retriever_module, "emit_stream_event", lambda *args, **kwargs: None, raising=True)
    monkeypatch.setattr(retriever_module, "get_vector_store", lambda: SimpleNamespace(search=lambda **kwargs: []), raising=True)

    retriever = HybridRetriever(
        tenant_id=tenant_id,
        account_id="member-1",
        dataset_id=dataset_id,
        retrieval_mode="hybrid",
        enable_reranker=False,
        sparse_enabled=False,
        dedup_enabled=False,
    )

    out = retriever._hybrid_search(
        "query",
        top_k=1,
        score_threshold=0.0,
        tenant_id=tenant_id,
        retrieval_mode="hybrid",
    )

    assert [item["content"] for item in out] == ["vector ok"]


def test_hybrid_search_propagates_retryable_timeout_when_all_runtime_shards_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.retriever as retriever_module
    from app.rag.retriever import HybridRetriever
    from app.services.rag_runtime_limiter import RetrievalAdmissionTimeoutError

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    runtime = _runtime("test-space")

    for name, value in {
        "RETRIEVAL_CANDIDATE_SINGLEFLIGHT_ENABLED": False,
        "RETRIEVAL_CANDIDATE_CACHE_ENABLED": False,
        "SEMANTIC_CACHE_ENABLED": False,
    }.items():
        monkeypatch.setattr(retriever_module.settings, name, value, raising=False)

    monkeypatch.setattr(HybridRetriever, "_explicit_dataset_scope_ids", lambda self: (dataset_id,), raising=True)  # noqa: ANN001
    monkeypatch.setattr(HybridRetriever, "_resolve_dataset_runtime_shards", lambda self, *, tenant_id, dataset_ids=None: [(runtime, (dataset_id,))], raising=True)  # noqa: ANN001,ARG005,E501
    monkeypatch.setattr(HybridRetriever, "_resolve_embedding_runtime", lambda self, *, tenant_id: runtime, raising=True)  # noqa: ANN001,ARG005
    monkeypatch.setattr(HybridRetriever, "_search_vector_runtime_shards", lambda self, **kwargs: ([], [RetrievalAdmissionTimeoutError(0.2)]), raising=True)  # noqa: ANN001
    monkeypatch.setattr(HybridRetriever, "_search_bm25", lambda self, **kwargs: [], raising=True)  # noqa: ANN001,ARG005
    monkeypatch.setattr(HybridRetriever, "_search_lexical_db", lambda self, **kwargs: [], raising=True)  # noqa: ANN001,ARG005
    monkeypatch.setattr(HybridRetriever, "_search_sparse", lambda self, **kwargs: [], raising=True)  # noqa: ANN001,ARG005
    monkeypatch.setattr(retriever_module, "emit_stream_event", lambda *args, **kwargs: None, raising=True)
    monkeypatch.setattr(retriever_module, "get_vector_store", lambda: SimpleNamespace(search=lambda **kwargs: []), raising=True)

    retriever = HybridRetriever(
        tenant_id=tenant_id,
        account_id="member-1",
        dataset_id=dataset_id,
        retrieval_mode="hybrid",
        enable_reranker=False,
        sparse_enabled=False,
        dedup_enabled=False,
    )

    with pytest.raises(RetrievalAdmissionTimeoutError):
        retriever._hybrid_search(
            "query",
            top_k=1,
            score_threshold=0.0,
            tenant_id=tenant_id,
            retrieval_mode="hybrid",
        )
