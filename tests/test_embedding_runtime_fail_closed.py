import datetime as _datetime
import uuid
from types import SimpleNamespace

import pytest

if not hasattr(_datetime, "UTC"):
    _datetime.UTC = _datetime.timezone.utc


def _runtime(*, dataset_scoped: bool, space: str = "space-a", collection: str = "documents_emb_space_a"):
    from app.services.dataset_embedding_config import DatasetEmbeddingRuntimeConfig

    return DatasetEmbeddingRuntimeConfig(
        provider="local",
        model="embed-model",
        api_base="",
        api_key="",
        embedding_space_hash=space,
        collection_name=collection,
        dataset_scoped=dataset_scoped,
    )


def _configure_retrieval(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings

    for name, value in {
        "BM25_INDEX_ENABLED": False,
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


def test_index_chunks_raises_when_scoped_document_runtime_cannot_be_resolved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.indexer as indexer_module
    from app.models.dataset import Dataset as DBDataset
    from app.models.document import Document as DBDocument
    from app.types.indexing import ChunkInput

    tenant_id = uuid.uuid4()
    document_id = uuid.uuid4()
    dataset_id = uuid.uuid4()

    class _Query:
        def __init__(self, result):  # noqa: ANN001
            self._result = result

        def filter(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            return self

        def first(self):  # noqa: ANN202
            if isinstance(self._result, BaseException):
                raise self._result
            return self._result

    class _DB:
        def __init__(self) -> None:
            self._query_calls = 0

        def query(self, *entities):  # noqa: ANN002, ANN003, ANN202
            self._query_calls += 1
            if self._query_calls == 1:
                assert entities == (DBDocument.dataset_id,)
                return _Query((dataset_id,))
            if self._query_calls == 2:
                assert entities == (DBDataset.dataset_metadata,)
                return _Query(RuntimeError("dataset metadata unavailable"))
            raise AssertionError("channel tracking query should not run before runtime resolution fails")

    indexer = indexer_module.Indexer.__new__(indexer_module.Indexer)
    indexer._db = _DB()
    monkeypatch.setattr(indexer_module.Indexer, "_resolve_chunk_vector_enabled", lambda self, options: False)
    monkeypatch.setattr(indexer_module.Indexer, "_resolve_bm25_enabled", lambda self, options: False)
    monkeypatch.setattr(indexer_module.Indexer, "_persist_document_chunks", lambda self, **kwargs: [])
    monkeypatch.setattr(indexer_module.Indexer, "_update_bm25_for_chunks", lambda self, **kwargs: None)

    with pytest.raises(RuntimeError, match="dataset-scoped embedding runtime"):
        indexer.index_chunks(
            document_id=document_id,
            tenant_id=tenant_id,
            chunks=[ChunkInput(content="chunk", metadata={})],
        )


def test_retriever_dataset_scope_raises_when_runtime_lookup_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.retriever as retriever_module
    from app.rag.retriever import HybridRetriever

    _configure_retrieval(monkeypatch)
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()

    monkeypatch.setattr(HybridRetriever, "_resolve_embedding_runtime", lambda self, *, tenant_id: _runtime(dataset_scoped=False))

    class _Query:
        def filter(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            return self

        def all(self):  # noqa: ANN202
            raise RuntimeError("dataset runtime query failed")

    class _Session:
        def query(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            return _Query()

        def close(self) -> None:
            return None

    monkeypatch.setattr(retriever_module, "SessionLocal", lambda: _Session(), raising=True)
    monkeypatch.setattr(retriever_module, "get_vector_store", lambda: SimpleNamespace(search=lambda **kwargs: []))

    retriever = HybridRetriever(
        tenant_id=tenant_id,
        account_id="member-1",
        dataset_ids=[dataset_id],
        retrieval_mode="vector",
        enable_reranker=False,
        sparse_enabled=False,
        dedup_enabled=False,
        k=1,
    )

    with pytest.raises(LookupError, match="dataset-scoped embedding runtime unavailable"):
        retriever._hybrid_search(
            "scope query",
            top_k=1,
            score_threshold=0.0,
            tenant_id=tenant_id,
            retrieval_mode="vector",
        )


def test_retriever_dataset_scope_rejects_malformed_runtime_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.retriever as retriever_module
    from app.rag.retriever import HybridRetriever

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()

    class _Query:
        def filter(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            return self

        def all(self):  # noqa: ANN202
            return [(dataset_id, ["invalid"])]

    class _Session:
        def query(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
            return _Query()

        def close(self) -> None:
            return None

    monkeypatch.setattr(retriever_module, "SessionLocal", lambda: _Session(), raising=True)

    with pytest.raises(LookupError, match="dataset-scoped embedding runtime invalid"):
        HybridRetriever(dataset_ids=[dataset_id])._resolve_dataset_runtime_shards(tenant_id=tenant_id)


def test_retriever_document_scope_raises_when_dataset_runtime_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.rag.retriever import HybridRetriever

    _configure_retrieval(monkeypatch)
    tenant_id = uuid.uuid4()
    document_id = uuid.uuid4()
    dataset_id = uuid.uuid4()

    monkeypatch.setattr(HybridRetriever, "_resolve_embedding_runtime", lambda self, *, tenant_id: _runtime(dataset_scoped=False))
    monkeypatch.setattr(
        HybridRetriever,
        "_resolve_document_dataset_scope",
        lambda self, *, tenant_id, document_ids: ((dataset_id,), False),  # noqa: ARG005
    )
    monkeypatch.setattr(HybridRetriever, "_resolve_dataset_runtime_shards", lambda self, *, tenant_id, dataset_ids=None: [])  # noqa: ARG005

    retriever = HybridRetriever(
        tenant_id=tenant_id,
        account_id="member-1",
        document_ids=[document_id],
        retrieval_mode="vector",
        enable_reranker=False,
        sparse_enabled=False,
        dedup_enabled=False,
        k=1,
    )

    with pytest.raises(LookupError, match="dataset-scoped embedding runtime"):
        retriever._hybrid_search(
            "scope query",
            top_k=1,
            score_threshold=0.0,
            document_ids=[document_id],
            tenant_id=tenant_id,
            retrieval_mode="vector",
        )
