import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.rag.retrieval.recall import channel_collection


class ScopedDB:
    def __init__(self, *, tenant_id, documents=(), datasets=()):
        self.tenant_id = tenant_id
        self.documents = list(documents)
        self.datasets = list(datasets)
        self.reads = []
        self.closed = False

    def query(self, *columns):
        from app.models.datasets.records import Dataset

        rows = self.datasets if columns[0] is Dataset.id else self.documents
        db = self

        class Query:
            def filter(self, *conditions):
                tenant_condition = next(
                    condition for condition in conditions if str(condition.left).endswith("tenant_id")
                )
                assert tenant_condition.right.value == db.tenant_id
                db.reads.append(columns)
                return self

            def all(self):
                return rows

        return Query()

    def close(self):
        self.closed = True


def test_runtime_scope_owns_document_resolution_shard_grouping_and_filters(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.infrastructure.config import settings
    from app.rag.retrieval.recall.runtime_scope import RetrievalScope, resolve_runtime_scope

    monkeypatch.setattr(settings, "VECTOR_BACKEND", "milvus")
    tenant_id, dataset_a, dataset_b, document_a, document_b = [uuid4() for _ in range(5)]
    db = ScopedDB(
        tenant_id=tenant_id,
        documents=[(document_a, dataset_a), (document_b, dataset_b)],
        datasets=[
            (dataset_a, {"embedding_defaults": {"provider": "local", "model": "model-a"}}),
            (dataset_b, {"embedding_defaults": {"provider": "local", "model": "model-b"}}),
        ],
    )
    scope = RetrievalScope(
        tenant_id=tenant_id,
        account_id="account-a",
        document_ids=(document_b, document_a),
        metadata_filter={"page": 2, "document_user.team": "research"},
    )
    resolved = resolve_runtime_scope(db, scope=scope)
    assert resolved.scope == scope
    assert set(resolved.runtime_dataset_ids) == {dataset_a, dataset_b}
    assert {shard.runtime.model for shard in resolved.runtime_shards} == {"model-a", "model-b"}
    assert {dataset_id for shard in resolved.runtime_shards for dataset_id in shard.dataset_ids} == {
        dataset_a,
        dataset_b,
    }
    assert resolved.metadata_filter == scope.metadata_filter
    assert resolved.keyword_filter == {"page": 2}
    assert resolved.vector_filter["page_number"] == 2
    assert "document_user.team" not in resolved.vector_filter
    assert resolved.corpus_scope.tenant_id == tenant_id
    assert resolved.corpus_scope.document_ids == scope.document_ids
    assert len(db.reads) == 2 and not db.closed
    with pytest.raises(FrozenInstanceError):
        scope.tenant_id = uuid4()


def test_missing_dataset_is_an_explicit_failure_instead_of_a_default_runtime() -> None:
    from app.rag.retrieval.recall.runtime_scope import RetrievalScope, resolve_runtime_scope

    tenant_id, dataset_id = uuid4(), uuid4()
    db = ScopedDB(tenant_id=tenant_id, datasets=[])
    with pytest.raises(LookupError, match="dataset-scoped embedding runtime unavailable"):
        resolve_runtime_scope(
            db, scope=RetrievalScope(tenant_id=tenant_id, account_id="account", dataset_ids=(dataset_id,))
        )
    assert not db.closed


def test_document_lookup_failure_keeps_its_cause_and_the_callers_session() -> None:
    from app.rag.retrieval.recall.runtime_scope import RetrievalScope, resolve_runtime_scope

    failure = RuntimeError("document database unavailable")

    def query(*_columns):
        raise failure

    db = SimpleNamespace(query=query, close=lambda: pytest.fail("closed caller session"))
    scope = RetrievalScope(tenant_id=uuid4(), account_id="account", document_ids=(uuid4(),))
    with pytest.raises(LookupError, match="dataset-scoped embedding runtime unavailable") as caught:
        resolve_runtime_scope(db, scope=scope)
    assert caught.value.__cause__ is failure


def test_reader_resolves_runtime_once_and_passes_that_runtime_to_enrichment(monkeypatch) -> None:
    from app.infrastructure.config import settings
    from app.rag.retrieval.recall import retriever as reader_module
    from app.rag.retrieval.recall import vector_search
    from app.rag.retrieval.recall.retriever import HybridRetriever

    for name in (
        "BM25_INDEX_ENABLED",
        "LEXICAL_DB_ENABLED",
        "COLBERT_RETRIEVAL_ENABLED",
        "COLPALI_RETRIEVAL_ENABLED",
        "SPARSE_RETRIEVAL_ENABLED",
        "RETRIEVAL_CANDIDATE_CACHE_ENABLED",
        "RETRIEVAL_CANDIDATE_SINGLEFLIGHT_ENABLED",
        "SEMANTIC_CACHE_ENABLED",
        "RAG_CONTEXT_STITCHING_ENABLED",
        "RETRIEVAL_GOVERNANCE_PREFER_AUTHORITY",
        "RETRIEVAL_GOVERNANCE_PREFER_LATEST",
        "RETRIEVAL_GOVERNANCE_FILTER_SUPERSEDED",
    ):
        monkeypatch.setattr(settings, name, False)
    tenant_id, dataset_id = uuid4(), uuid4()
    db = ScopedDB(
        tenant_id=tenant_id,
        datasets=[(dataset_id, {"embedding_defaults": {"provider": "local", "model": "one-runtime"}})],
    )
    monkeypatch.setattr(reader_module, "SessionLocal", lambda: db)
    monkeypatch.setattr(channel_collection, "get_vector_store", lambda: object())
    received = []
    hit = {
        "chunk_id": "chunk",
        "content": "kept",
        "score": 0.8,
        "metadata": {"document_id": str(uuid4()), "dataset_id": str(dataset_id)},
    }

    def vectors(request, *, runtime, shards, **kwargs):
        received.append(runtime)
        return vector_search.VectorSearchBatch([hit], (vector_search.VectorShardResult(shards[0], [hit], None, None),))

    def enrich(self, results, *, embedding_runtime=None, **kwargs):
        received.append(embedding_runtime)
        return results

    monkeypatch.setattr(vector_search, "search_vectors", vectors)
    monkeypatch.setattr(HybridRetriever, "_enrich_results_with_db_metadata", enrich)
    monkeypatch.setattr(HybridRetriever, "_expand_results_with_neighbors", lambda self, results: results)
    monkeypatch.setattr(HybridRetriever, "_auto_merge_parent_child", lambda self, results: results)
    reader = HybridRetriever(
        tenant_id=tenant_id,
        account_id="actor",
        dataset_id=dataset_id,
        retrieval_mode="vector",
        enable_reranker=False,
        enable_weight_rerank=False,
    )
    assert [doc.page_content for doc in reader.invoke("ordinary")] == ["kept"]
    assert len(db.reads) == 1
    assert len(received) >= 2 and all(runtime is received[0] for runtime in received)
    assert received[0].model == "one-runtime"


def test_concurrent_reader_debug_uses_its_returned_batch_after_other_call_completes(monkeypatch) -> None:
    from app.infrastructure.config import settings
    from app.rag.retrieval.recall import candidate_retrieval
    from app.rag.retrieval.recall import retriever as reader_module
    from app.rag.retrieval.recall.channel_diagnostics import empty_channel_metrics
    from app.rag.retrieval.recall.retriever import HybridRetriever
    from tests.candidate_fixtures import completed_candidate_batch

    for name in (
        "RAG_CONTEXT_STITCHING_ENABLED",
        "RETRIEVAL_GOVERNANCE_PREFER_AUTHORITY",
        "RETRIEVAL_GOVERNANCE_PREFER_LATEST",
        "RETRIEVAL_GOVERNANCE_FILTER_SUPERSEDED",
        "RETRIEVAL_COMPACT_HIGH_CONFIDENCE_ENABLED",
    ):
        monkeypatch.setattr(settings, name, False)
    tenant_id, dataset_id = uuid4(), uuid4()
    monkeypatch.setattr(
        reader_module, "SessionLocal", lambda: ScopedDB(tenant_id=tenant_id, datasets=[(dataset_id, {})])
    )
    barrier = threading.Barrier(2)
    debug_by_query = {}

    def retrieve(request, **kwargs):
        count = 2 if request.query == "first" else 1
        records = [
            {
                "chunk_id": request.query + str(index),
                "content": request.query,
                "score": 0.8,
                "metadata": {"document_id": str(uuid4()), "dataset_id": str(dataset_id)},
            }
            for index in range(count)
        ]
        metrics = empty_channel_metrics()
        metrics["counts"]["vector_candidates"] = count
        return completed_candidate_batch(request, records, channel_metrics=metrics)

    record_debug = HybridRetriever._record_hybrid_debug_metrics

    def record_after_both_complete(self, debug, batch):
        barrier.wait(timeout=3)
        record_debug(self, debug, batch)
        debug_by_query[debug["query_normalization"]["normalized"]] = debug["counts"]["vector_candidates"]

    monkeypatch.setattr(candidate_retrieval, "retrieve_candidates", retrieve)
    monkeypatch.setattr(HybridRetriever, "_record_hybrid_debug_metrics", record_after_both_complete)
    monkeypatch.setattr(HybridRetriever, "_enrich_results_with_db_metadata", lambda self, records, **kwargs: records)
    monkeypatch.setattr(HybridRetriever, "_expand_results_with_neighbors", lambda self, records: records)
    monkeypatch.setattr(HybridRetriever, "_auto_merge_parent_child", lambda self, records: records)
    reader = HybridRetriever(tenant_id=tenant_id, account_id="actor", dataset_id=dataset_id, k=3, enable_reranker=False)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(reader.invoke, ("first", "second")))
    assert [[doc.page_content for doc in docs] for docs in results] == [["first", "first"], ["second"]]
    assert debug_by_query == {"first": 2, "second": 1}


def test_legacy_unscoped_documents_preserve_the_runtime_coverage_admission_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.infrastructure.config import settings
    from app.rag.retrieval.recall import retriever as retriever_module
    from app.rag.retrieval.recall.retriever import HybridRetriever

    for name, value in {
        "VECTOR_BACKEND": "milvus",
        "BM25_INDEX_ENABLED": False,
        "LEXICAL_DB_ENABLED": False,
        "SPARSE_RETRIEVAL_ENABLED": False,
        "COLBERT_RETRIEVAL_ENABLED": False,
        "COLPALI_RETRIEVAL_ENABLED": False,
        "RETRIEVAL_CANDIDATE_CACHE_ENABLED": False,
        "RETRIEVAL_CANDIDATE_SINGLEFLIGHT_ENABLED": False,
        "SEMANTIC_CACHE_ENABLED": False,
    }.items():
        monkeypatch.setattr(settings, name, value)
    tenant_id, dataset_id, scoped_document, unscoped_document = [uuid4() for _ in range(4)]
    db = ScopedDB(
        tenant_id=tenant_id,
        documents=[(scoped_document, dataset_id), (unscoped_document, None)],
        datasets=[(dataset_id, {})],
    )
    calls = []
    monkeypatch.setattr(retriever_module, "SessionLocal", lambda: db)
    monkeypatch.setattr(
        channel_collection,
        "get_vector_store",
        lambda: SimpleNamespace(search=lambda **_kwargs: calls.append("vector") or []),
    )
    retriever = HybridRetriever(
        tenant_id=tenant_id,
        account_id="account",
        document_ids=[scoped_document, unscoped_document],
        retrieval_mode="vector",
        enable_reranker=False,
        sparse_enabled=False,
        dedup_enabled=False,
    )
    with pytest.raises(LookupError, match="dataset-scoped embedding runtime unavailable"):
        retriever._hybrid_search(
            "scope query",
            top_k=1,
            score_threshold=0.0,
            tenant_id=tenant_id,
            document_ids=[scoped_document, unscoped_document],
            retrieval_mode="vector",
        )
    assert calls == []
    assert db.closed
