import uuid
from types import SimpleNamespace

import pytest
from langchain_core.documents import Document


def _bare_retriever():
    from app.rag.retriever import HybridRetriever

    return HybridRetriever.__new__(HybridRetriever)


def test_rebuild_persisted_retrieval_indexes_blocks_scope_over_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.rag.retriever import HybridRetriever

    retriever = _bare_retriever()
    tenant_id = uuid.uuid4()
    load_calls: list[bool] = []
    build_calls: list[bool] = []

    monkeypatch.setattr("app.rag.retriever.settings.RETRIEVAL_REBUILD_MAX_CHUNKS", 2, raising=False)
    monkeypatch.setattr(HybridRetriever, "_count_retrieval_docs_in_db", lambda self, db, **kwargs: 3, raising=True)  # noqa: ANN001,ARG005
    monkeypatch.setattr(
        HybridRetriever,
        "_load_retrieval_docs_from_db",
        lambda self, db, **kwargs: load_calls.append(True) or [],  # noqa: ANN001,ARG005
        raising=True,
    )
    monkeypatch.setattr(
        HybridRetriever,
        "_build_bm25_index_from_documents",
        lambda self, docs, **kwargs: build_calls.append(True),  # noqa: ANN001,ARG005
        raising=True,
    )

    with pytest.raises(RuntimeError, match="RETRIEVAL_REBUILD_MAX_CHUNKS=2"):
        retriever.rebuild_persisted_retrieval_indexes(object(), tenant_id=tenant_id, batch_size=32)

    assert load_calls == []
    assert build_calls == []


def test_rebuild_persisted_retrieval_indexes_rechecks_cap_after_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.rag.retriever import HybridRetriever

    retriever = _bare_retriever()
    tenant_id = uuid.uuid4()
    docs = [
        Document(page_content="one", id="chunk-1", metadata={"document_id": "doc-1", "chunk_index": 0}),
        Document(page_content="two", id="chunk-2", metadata={"document_id": "doc-1", "chunk_index": 1}),
        Document(page_content="three", id="chunk-3", metadata={"document_id": "doc-2", "chunk_index": 0}),
    ]
    load_limits: list[int] = []
    build_calls: list[bool] = []

    monkeypatch.setattr("app.rag.retriever.settings.RETRIEVAL_REBUILD_MAX_CHUNKS", 2, raising=False)
    monkeypatch.setattr(HybridRetriever, "_count_retrieval_docs_in_db", lambda self, db, **kwargs: 2, raising=True)  # noqa: ANN001,ARG005

    def _load(self, db, **kwargs):  # noqa: ANN001,ANN202
        load_limits.append(int(kwargs.get("max_chunks") or 0))
        return list(docs)

    monkeypatch.setattr(HybridRetriever, "_load_retrieval_docs_from_db", _load, raising=True)
    monkeypatch.setattr(
        HybridRetriever,
        "_build_bm25_index_from_documents",
        lambda self, docs, **kwargs: build_calls.append(True),  # noqa: ANN001,ARG005
        raising=True,
    )

    with pytest.raises(RuntimeError, match="RETRIEVAL_REBUILD_MAX_CHUNKS=2"):
        retriever.rebuild_persisted_retrieval_indexes(object(), tenant_id=tenant_id, batch_size=16)

    assert load_limits == [3]
    assert build_calls == []


def test_disabled_rebuild_cap_skips_the_count_query(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.rag.retriever import HybridRetriever

    retriever = _bare_retriever()
    monkeypatch.setattr("app.rag.retriever.settings.RETRIEVAL_REBUILD_MAX_CHUNKS", 0, raising=False)
    monkeypatch.setattr(
        HybridRetriever,
        "_count_retrieval_docs_in_db",
        lambda *args, **kwargs: pytest.fail("count should be skipped"),
        raising=True,
    )
    monkeypatch.setattr(HybridRetriever, "_load_retrieval_docs_from_db", lambda self, db, **kwargs: [], raising=True)  # noqa: ANN001,ARG005,E501

    assert retriever._load_retrieval_docs_for_rebuild(object(), tenant_id=uuid.uuid4()) == []


def test_rebuild_persisted_retrieval_indexes_builds_under_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.rag.retriever import HybridRetriever

    retriever = _bare_retriever()
    tenant_id = uuid.uuid4()
    docs = [
        Document(page_content="one", id="chunk-1", metadata={"document_id": "doc-1", "chunk_index": 0}),
        Document(page_content="two", id="chunk-2", metadata={"document_id": "doc-2", "chunk_index": 0}),
    ]
    bm25_calls: list[tuple[str, int]] = []

    monkeypatch.setattr("app.rag.retriever.settings.RETRIEVAL_REBUILD_MAX_CHUNKS", 2, raising=False)
    monkeypatch.setattr(HybridRetriever, "_count_retrieval_docs_in_db", lambda self, db, **kwargs: 2, raising=True)  # noqa: ANN001,ARG005
    monkeypatch.setattr(HybridRetriever, "_load_retrieval_docs_from_db", lambda self, db, **kwargs: list(docs), raising=True)  # noqa: ANN001,ARG005
    monkeypatch.setattr(
        HybridRetriever,
        "_build_bm25_index_from_documents",
        lambda self, items, *, tenant_id=None, cache_key=None: bm25_calls.append((str(cache_key), len(items))),  # noqa: ANN001
        raising=True,
    )
    monkeypatch.setattr("app.rag.retriever.settings.SPARSE_RETRIEVAL_ENABLED", False, raising=False)
    monkeypatch.setattr("app.rag.retriever.settings.COLBERT_RETRIEVAL_ENABLED", False, raising=False)

    result = retriever.rebuild_persisted_retrieval_indexes(object(), tenant_id=tenant_id, batch_size=8)

    assert result["doc_count"] == 2
    assert result["bm25_rebuilt"] is True
    assert bm25_calls and bm25_calls[0][1] == 2


def test_indexer_rebuild_chunk_indexes_uses_operational_rebuild_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.indexer as indexer_module

    tenant_id = uuid.uuid4()
    doc_ids = [uuid.uuid4(), uuid.uuid4()]
    touched: list[uuid.UUID] = []
    helper_calls: list[dict[str, object]] = []

    indexer = indexer_module.Indexer.__new__(indexer_module.Indexer)
    indexer._db = SimpleNamespace(flush=lambda: None)
    indexer._touch_chunk_retrieval_scope = lambda **kwargs: touched.append(kwargs["document_id"])  # type: ignore[method-assign]

    monkeypatch.setattr(indexer_module.settings, "BM25_INDEX_ENABLED", True, raising=False)
    monkeypatch.setattr(
        type(indexer_module.hybrid_retriever),
        "rebuild_bm25_index_for_operational_scope",
        lambda self, db, **kwargs: helper_calls.append(kwargs) or 2,  # noqa: ANN001,ANN202
        raising=True,
    )

    indexer.rebuild_chunk_indexes(tenant_id=tenant_id, document_ids=doc_ids)

    assert helper_calls == [{"tenant_id": tenant_id, "document_ids": doc_ids, "batch_size": 2000}]
    assert touched == doc_ids
