from types import SimpleNamespace
from unittest.mock import ANY
from uuid import uuid4

import pytest


def test_delete_chunk_indexes_strict_propagates_backend_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import indexer

    def _fail_scoped_delete(*_args, **_kwargs) -> None:  # noqa: ANN002, ANN003
        raise RuntimeError("vector backend unavailable")

    class _VectorStore:
        def delete_by_document_id(self, *_args, **_kwargs) -> None:  # noqa: ANN002, ANN003
            return None

    monkeypatch.setattr(indexer.Indexer, "_delete_dataset_scoped_chunk_vectors", _fail_scoped_delete)
    monkeypatch.setattr(indexer, "get_vector_store", lambda: _VectorStore())
    monkeypatch.setattr(
        type(indexer.hybrid_retriever),
        "remove_document_from_bm25_index",
        lambda *_a, **_k: None,
    )
    service = object.__new__(indexer.Indexer)

    with pytest.raises(RuntimeError, match="Document index cleanup failed"):
        service.delete_chunk_indexes(tenant_id=uuid4(), document_id=uuid4(), strict=True)


def test_delete_chunk_indexes_ignores_invalid_dataset_scoped_embedding_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import indexer

    def _invalid_runtime(*_args, **_kwargs) -> None:  # noqa: ANN002, ANN003
        raise ValueError("dataset-scoped embedding_defaults require VECTOR_BACKEND=milvus")

    class _VectorStore:
        def delete_by_document_id(self, *_args, **_kwargs) -> None:  # noqa: ANN002, ANN003
            return None

    monkeypatch.setattr(indexer.Indexer, "_embedding_runtime_for_document", _invalid_runtime)
    monkeypatch.setattr(indexer, "get_vector_store", lambda: _VectorStore())
    monkeypatch.setattr(
        type(indexer.hybrid_retriever),
        "remove_document_from_bm25_index",
        lambda *_a, **_k: None,
    )
    service = object.__new__(indexer.Indexer)

    service.delete_chunk_indexes(tenant_id=uuid4(), document_id=uuid4(), strict=True)


def test_delete_chunk_indexes_invalidates_scope_after_partial_backend_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import indexer

    def _fail_scoped_delete(*_args, **_kwargs) -> None:  # noqa: ANN002, ANN003
        raise RuntimeError("vector backend unavailable")

    class _VectorStore:
        def delete_by_document_id(self, *_args, **_kwargs) -> None:  # noqa: ANN002, ANN003
            return None

    flushed: list[bool] = []
    touched: list[tuple] = []
    monkeypatch.setattr(indexer.Indexer, "_delete_dataset_scoped_chunk_vectors", _fail_scoped_delete)
    monkeypatch.setattr(indexer, "get_vector_store", lambda: _VectorStore())
    monkeypatch.setattr(
        type(indexer.hybrid_retriever),
        "remove_document_from_bm25_index",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        indexer.Indexer,
        "_touch_chunk_retrieval_scope",
        lambda _self, **kwargs: touched.append((kwargs["tenant_id"], kwargs["document_id"])),
    )
    service = object.__new__(indexer.Indexer)
    service._db = SimpleNamespace(flush=lambda: flushed.append(True))
    tenant_id = uuid4()
    document_id = uuid4()

    service.delete_chunk_indexes(tenant_id=tenant_id, document_id=document_id)

    assert touched == [(tenant_id, document_id)]
    assert flushed == [True]


def test_touch_chunk_retrieval_scope_updates_document_and_dataset_timestamps() -> None:
    from app.services import indexer

    tenant_id = uuid4()
    document_id = uuid4()
    dataset_id = uuid4()
    document = SimpleNamespace(dataset_id=dataset_id, updated_at=None)
    dataset = SimpleNamespace(updated_at=None)

    class _Query:
        def __init__(self, row) -> None:  # noqa: ANN001
            self._row = row

        def filter(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
            return self

        def first(self):
            return self._row

    class _DB:
        def query(self, model):  # noqa: ANN001
            if model is indexer.DBDocument:
                return _Query(document)
            if model is indexer.DBDataset:
                return _Query(dataset)
            raise AssertionError(f"unexpected model: {model}")

    service = object.__new__(indexer.Indexer)
    service._db = _DB()

    service._touch_chunk_retrieval_scope(tenant_id=tenant_id, document_id=document_id)

    assert document.updated_at is not None
    assert dataset.updated_at == document.updated_at


def test_persist_document_chunks_touches_retrieval_scope_before_commit() -> None:
    from app.services import indexer
    from app.types.indexing import ChunkInput

    events: list[str] = []

    class _DB:
        def add_all(self, _items) -> None:  # noqa: ANN001
            events.append("add")

        def flush(self) -> None:
            events.append("flush")

        def commit(self) -> None:
            events.append("commit")

    service = object.__new__(indexer.Indexer)
    service._db = _DB()
    service._touch_chunk_retrieval_scope = lambda **_kwargs: events.append("touch")  # type: ignore[method-assign]

    service._persist_document_chunks(
        document_id=uuid4(),
        tenant_id=uuid4(),
        dataset_id=uuid4(),
        chunks=[ChunkInput(content="content", metadata={})],
    )

    assert events == ["add", "touch", "flush", "commit"]


def test_non_milvus_delete_skips_legacy_dataset_embedding_config(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import indexer

    monkeypatch.setattr(indexer.settings, "VECTOR_BACKEND", "faiss", raising=False)
    monkeypatch.setattr(
        indexer.Indexer,
        "_embedding_runtime_for_document",
        lambda *_a, **_k: pytest.fail("non-Milvus cleanup must not resolve dataset-scoped embeddings"),
    )
    service = object.__new__(indexer.Indexer)

    service._delete_dataset_scoped_chunk_vectors(tenant_id=uuid4(), document_id=uuid4())


def test_delete_dataset_scoped_chunk_vectors_uses_persisted_chunk_space_on_runtime_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import indexer
    from app.services.dataset_embedding_config import DatasetEmbeddingRuntimeConfig

    tenant_id = uuid4()
    document_id = uuid4()
    deleted: list[str] = []

    class _Adapter:
        def __init__(self, collection_name: str) -> None:
            self.collection_name = collection_name

        def delete_by_document_id(self, doc_id, tenant_id=None) -> None:  # noqa: ANN001
            assert doc_id == document_id
            assert tenant_id == test_tenant_id
            deleted.append(self.collection_name)

    class _Query:
        def filter(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
            return self

        def all(self):
            return [({"embedding_space_hash": "space-a"},)]

    test_tenant_id = tenant_id
    monkeypatch.setattr(indexer.settings, "VECTOR_BACKEND", "milvus", raising=False)
    monkeypatch.setattr(indexer, "resolve_collection_name", lambda name: name)
    monkeypatch.setattr(indexer, "get_milvus_adapter", lambda name: _Adapter(name))
    monkeypatch.setattr(
        indexer,
        "resolve_dataset_embedding_runtime",
        lambda _meta: DatasetEmbeddingRuntimeConfig(
            provider="local",
            model="model-default",
            api_base="",
            api_key="",
            embedding_space_hash="space-default",
            collection_name="documents",
            dataset_scoped=False,
        ),
    )
    monkeypatch.setattr(
        indexer.Indexer,
        "_embedding_runtime_for_document",
        lambda *_a, **_k: DatasetEmbeddingRuntimeConfig(
            provider="local",
            model="model-default",
            api_base="",
            api_key="",
            embedding_space_hash="space-default",
            collection_name="documents",
            dataset_scoped=False,
        ),
    )
    service = object.__new__(indexer.Indexer)
    service._db = SimpleNamespace(query=lambda *_a, **_k: _Query())

    service._delete_dataset_scoped_chunk_vectors(tenant_id=tenant_id, document_id=document_id)

    assert deleted == ["documents_emb_space_a"]


def test_delete_dataset_scoped_chunk_vectors_prefers_persisted_collection_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import indexer
    from app.services.dataset_embedding_config import DatasetEmbeddingRuntimeConfig

    tenant_id = uuid4()
    document_id = uuid4()
    deleted: list[str] = []

    class _Adapter:
        def __init__(self, collection_name: str) -> None:
            self.collection_name = collection_name

        def delete_by_document_id(self, doc_id, tenant_id=None) -> None:  # noqa: ANN001
            assert doc_id == document_id
            assert tenant_id == test_tenant_id
            deleted.append(self.collection_name)

    class _Row:
        def __init__(self, metadata: dict[str, object]) -> None:
            self._mapping = {"metadata": metadata}

        def __getitem__(self, key):  # noqa: ANN001
            return self._mapping[key]

    class _Query:
        def filter(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
            return self

        def all(self):
            return [_Row({"dataset_scoped": True, "vector_collection_name": "documents_emb_oldbase_space_a"})]

    test_tenant_id = tenant_id
    monkeypatch.setattr(indexer.settings, "VECTOR_BACKEND", "milvus", raising=False)
    monkeypatch.setattr(indexer, "resolve_collection_name", lambda name: name)
    monkeypatch.setattr(indexer, "get_milvus_adapter", lambda name: _Adapter(name))
    monkeypatch.setattr(
        indexer.Indexer,
        "_embedding_runtime_for_document",
        lambda *_a, **_k: DatasetEmbeddingRuntimeConfig(
            provider="local",
            model="model-b",
            api_base="",
            api_key="",
            embedding_space_hash="space-b",
            collection_name="documents_emb_space_b",
            dataset_scoped=True,
        ),
    )
    service = object.__new__(indexer.Indexer)
    service._db = SimpleNamespace(query=lambda *_a, **_k: _Query())

    service._delete_dataset_scoped_chunk_vectors(tenant_id=tenant_id, document_id=document_id)

    assert deleted == ["documents_emb_oldbase_space_a"]


def test_delete_dataset_scoped_chunk_vectors_rejects_ambiguous_default_space_without_scoped_marker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import indexer
    from app.services.dataset_embedding_config import DatasetEmbeddingRuntimeConfig

    tenant_id = uuid4()
    document_id = uuid4()

    class _Query:
        def filter(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
            return self

        def all(self):
            return [({"embedding_space_hash": "space-default"},)]

    monkeypatch.setattr(indexer.settings, "VECTOR_BACKEND", "milvus", raising=False)
    monkeypatch.setattr(
        indexer,
        "resolve_dataset_embedding_runtime",
        lambda _meta: DatasetEmbeddingRuntimeConfig(
            provider="local",
            model="model-default",
            api_base="",
            api_key="",
            embedding_space_hash="space-default",
            collection_name="documents",
            dataset_scoped=False,
        ),
    )
    monkeypatch.setattr(
        indexer.Indexer,
        "_embedding_runtime_for_document",
        lambda *_a, **_k: DatasetEmbeddingRuntimeConfig(
            provider="local",
            model="model-default",
            api_base="",
            api_key="",
            embedding_space_hash="space-default",
            collection_name="documents",
            dataset_scoped=False,
        ),
    )
    service = object.__new__(indexer.Indexer)
    service._db = SimpleNamespace(query=lambda *_a, **_k: _Query())

    with pytest.raises(
        indexer.DatasetScopedEmbeddingRuntimeResolutionError,
        match="cleanup target ambiguous",
    ):
        service._delete_dataset_scoped_chunk_vectors(tenant_id=tenant_id, document_id=document_id)


def test_upsert_document_chunk_vector_uses_dataset_scoped_collection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import indexer
    from app.services.dataset_embedding_config import DatasetEmbeddingRuntimeConfig

    tenant_id = uuid4()
    document_id = uuid4()
    runtime = DatasetEmbeddingRuntimeConfig(
        provider="local",
        model="model-custom",
        api_base="",
        api_key="",
        embedding_space_hash="space-custom",
        collection_name="documents_emb_space_custom",
        dataset_scoped=True,
    )
    writes: list[dict[str, object]] = []

    monkeypatch.setattr(indexer.settings, "VECTOR_BACKEND", "milvus", raising=False)
    monkeypatch.setattr(indexer.Indexer, "_embedding_runtime_for_document", lambda *_a, **_k: runtime)
    monkeypatch.setattr(
        indexer,
        "create_embeddings_for_runtime",
        lambda _runtime: SimpleNamespace(embed_documents=lambda texts: [[float(len(text))] for text in texts]),
    )
    monkeypatch.setattr(indexer, "resolve_collection_name", lambda name: name)
    monkeypatch.setattr(
        indexer,
        "get_milvus_adapter",
        lambda name: SimpleNamespace(
            add_vectors=lambda items, embeddings, batch_size, upsert: writes.append(
                {
                    "collection": name,
                    "items": items,
                    "embeddings": embeddings,
                    "batch_size": batch_size,
                    "upsert": upsert,
                }
            )
            or ["vector-1"]
        ),
    )
    monkeypatch.setattr(
        indexer,
        "get_vector_store",
        lambda: pytest.fail("dataset-scoped chunk upsert must not use the default vector store"),
    )

    service = object.__new__(indexer.Indexer)

    metadata = {"chunk_id": "chunk-1", "chunk_index": 7, "dataset_id": "dataset-1"}
    vector_id = service.upsert_document_chunk_vector(
        document_id=document_id,
        tenant_id=tenant_id,
        content="chunk text",
        metadata=metadata,
    )

    assert vector_id == "vector-1"
    assert metadata["embedding_space_hash"] == runtime.embedding_space_hash
    assert metadata["dataset_scoped"] is True
    assert metadata["vector_collection_name"] == runtime.collection_name
    assert writes == [
        {
            "collection": runtime.collection_name,
            "items": [
                {
                    "id": "chunk-1",
                    "content": "chunk text",
                    "metadata": {
                        "tenant_id": str(tenant_id),
                        "dataset_id": "dataset-1",
                        "embedding_space_hash": "space-custom",
                        "document_id": str(document_id),
                        "chunk_index": 7,
                        "chunk_id": "chunk-1",
                        "pipeline_hash": "",
                        "doc_pipeline_key": str(document_id),
                        "page_number": 0,
                        "source": "unknown",
                        "file_type": "unknown",
                        "img_id": "",
                        "image_id": "",
                        "image_url": "",
                    },
                }
            ],
            "embeddings": [[10.0]],
            "batch_size": ANY,
            "upsert": True,
        }
    ]


def test_upsert_document_chunk_vector_does_not_fall_back_on_runtime_lookup_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import indexer

    class _FailingDB:
        def query(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN201
            raise RuntimeError("database unavailable")

    monkeypatch.setattr(
        indexer,
        "get_vector_store",
        lambda: pytest.fail("runtime lookup failure must not write to the default vector store"),
    )
    service = object.__new__(indexer.Indexer)
    service._db = _FailingDB()

    with pytest.raises(
        indexer.DatasetScopedEmbeddingRuntimeResolutionError,
        match="dataset-scoped embedding runtime unavailable",
    ):
        service.upsert_document_chunk_vector(
            document_id=uuid4(),
            tenant_id=uuid4(),
            content="chunk text",
            metadata={"chunk_id": "chunk-1"},
        )


def test_delete_document_chunk_vectors_cleans_scoped_and_default_collections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import indexer

    tenant_id = uuid4()
    document_id = uuid4()
    deletes: list[dict[str, object]] = []

    monkeypatch.setattr(indexer.settings, "VECTOR_BACKEND", "milvus", raising=False)
    monkeypatch.setattr(
        indexer.Indexer,
        "_delete_dataset_scoped_chunk_vectors",
        lambda _self, **kwargs: deletes.append({"store": "scoped", **kwargs}),
    )
    monkeypatch.setattr(
        indexer,
        "get_vector_store",
        lambda: SimpleNamespace(
            delete_by_document_id_and_filter=lambda **kwargs: deletes.append(
                {"store": "default", **kwargs}
            )
        ),
    )

    service = object.__new__(indexer.Indexer)
    service.delete_document_chunk_vectors(
        tenant_id=tenant_id,
        document_id=document_id,
        metadata_filter={"chunk_id": {"$eq": "chunk-1"}},
    )

    assert deletes == [
        {
            "store": "scoped",
            "tenant_id": tenant_id,
            "document_id": document_id,
            "metadata_filter": {"chunk_id": {"$eq": "chunk-1"}},
        },
        {
            "store": "default",
            "tenant_id": tenant_id,
            "document_id": document_id,
            "metadata_filter": {"chunk_id": {"$eq": "chunk-1"}},
        },
    ]
