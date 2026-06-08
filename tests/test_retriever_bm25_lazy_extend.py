from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from langchain_core.documents import Document

from app.core.config import settings
from app.rag.retriever import HybridRetriever


class _FakeChunk:
    def __init__(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        chunk_index: int,
        content: str,
        chunk_id: UUID | None = None,
    ) -> None:
        self.tenant_id = tenant_id
        self.document_id = document_id
        self.chunk_index = chunk_index
        self.content = content
        self.id = chunk_id or uuid4()
        self.page_number = None
        self.doc_metadata = {}


class _FakeQuery:
    def __init__(self, results: list[_FakeChunk]) -> None:
        self._results = results

    def join(self, *_args, **_kwargs):
        return self

    def filter(self, *_args, **_kwargs):
        return self

    def order_by(self, *_args, **_kwargs):
        return self

    def limit(self, *_args, **_kwargs):
        return self

    def all(self):
        return list(self._results)


class _FakeSession:
    def __init__(self, results: list[_FakeChunk]) -> None:
        self._results = results
        self.closed = False

    def query(self, *_args, **_kwargs):
        return _FakeQuery(self._results)

    def close(self):
        self.closed = True


def test_bm25_lazy_build_extends_partial_cache(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "BM25_INDEX_ENABLED", True)
    monkeypatch.setattr(settings, "BM25_LAZY_BUILD_ENABLED", True)

    tenant_id = uuid4()
    doc1_id = uuid4()
    doc2_id = uuid4()

    retriever = HybridRetriever()

    # Seed BM25 cache with doc1 only.
    retriever.upsert_bm25_documents(
        [
            Document(
                page_content="doc1 content",
                id=str(uuid4()),
                metadata={"tenant_id": str(tenant_id), "document_id": str(doc1_id), "chunk_index": 0},
            )
        ],
        tenant_id=tenant_id,
    )

    fake_chunks = [
        _FakeChunk(tenant_id=tenant_id, document_id=doc2_id, chunk_index=0, content="doc2 content"),
    ]
    monkeypatch.setattr("app.rag.retriever.SessionLocal", lambda: _FakeSession(fake_chunks))

    ok = retriever._lazy_build_bm25_index(tenant_id=tenant_id, document_ids=[doc1_id, doc2_id])
    assert ok is True

    tenant_key = retriever._tenant_key(tenant_id)
    doc_ids = retriever._bm25_doc_ids.get(tenant_key) or set()
    assert str(doc1_id) in doc_ids
    assert str(doc2_id) in doc_ids


def test_bm25_search_reports_lazy_build_status(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "BM25_INDEX_ENABLED", True)
    monkeypatch.setattr(settings, "BM25_LAZY_BUILD_ENABLED", True)

    tenant_id = uuid4()
    doc_id = uuid4()
    chunk_id = uuid4()
    fake_chunks = [
        _FakeChunk(
            tenant_id=tenant_id,
            document_id=doc_id,
            chunk_index=0,
            content="doc2 content",
            chunk_id=chunk_id,
        ),
    ]
    monkeypatch.setattr("app.rag.retriever.SessionLocal", lambda: _FakeSession(fake_chunks))

    retriever = HybridRetriever()
    results = retriever._search_bm25(query="doc2", top_k=5, tenant_id=tenant_id, document_ids=[doc_id])

    assert results
    status = retriever._last_bm25_status
    assert status["index_enabled"] is True
    assert status["lazy_build_enabled"] is True
    assert status["lazy_build_attempted"] is True
    assert status["lazy_build_success"] is True
    assert status["cache_ready_after"] is True
    assert status["scope"] == "documents"
    assert status["document_scope_count"] == 1
    assert status["indexed_docs"] == 1
    assert status["reason"] == "ok"


def test_bm25_search_lazy_builds_single_dataset_from_metadata_filter(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "BM25_INDEX_ENABLED", True)
    monkeypatch.setattr(settings, "BM25_LAZY_BUILD_ENABLED", True)
    monkeypatch.setattr(settings, "BM25_LAZY_BUILD_FULL_TENANT", False)

    tenant_id = uuid4()
    dataset_id = uuid4()
    doc_id = uuid4()
    chunk_id = uuid4()
    fake_chunks = [
        _FakeChunk(
            tenant_id=tenant_id,
            document_id=doc_id,
            chunk_index=0,
            content="残疾人服务 一件事 申请材料",
            chunk_id=chunk_id,
        ),
    ]
    fake_chunks[0].doc_metadata = {"dataset_id": str(dataset_id)}
    monkeypatch.setattr("app.rag.retriever.SessionLocal", lambda: _FakeSession(fake_chunks))

    retriever = HybridRetriever()
    results = retriever._search_bm25(
        query="申请材料",
        top_k=5,
        tenant_id=tenant_id,
        metadata_filter={"dataset_id": str(dataset_id)},
    )

    assert results
    status = retriever._last_bm25_status
    assert status["lazy_build_attempted"] is True
    assert status["lazy_build_success"] is True
    assert status["scope"] == "dataset"
    assert status["dataset_scope"] is True
