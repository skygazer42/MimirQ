from types import SimpleNamespace
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
