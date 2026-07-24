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
