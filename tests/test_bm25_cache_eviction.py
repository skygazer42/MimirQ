from __future__ import annotations

from uuid import uuid4

from langchain_core.documents import Document


def _doc(doc_id: str) -> Document:
    # Minimal metadata needed by the retriever for lookup mapping.
    return Document(
        page_content=f"content for {doc_id}",
        id=doc_id,
        metadata={"document_id": doc_id, "chunk_index": 0},
    )


def test_bm25_cache_eviction_respects_max_tenants(monkeypatch) -> None:
    from app.core.config import settings
    from app.rag.retriever import HybridRetriever

    monkeypatch.setattr(settings, "BM25_CACHE_MAX_TENANTS", 2, raising=False)

    r = HybridRetriever()
    t1, t2, t3 = uuid4(), uuid4(), uuid4()

    r.upsert_bm25_documents([_doc("d1")], tenant_id=t1)
    r.upsert_bm25_documents([_doc("d2")], tenant_id=t2)
    assert str(t1) in r._bm25_retrievers
    assert str(t2) in r._bm25_retrievers

    # Third tenant should evict the least-recently used (t1).
    r.upsert_bm25_documents([_doc("d3")], tenant_id=t3)
    assert len(r._bm25_retrievers) == 2
    assert str(t1) not in r._bm25_retrievers
    assert str(t2) in r._bm25_retrievers
    assert str(t3) in r._bm25_retrievers


def test_bm25_cache_eviction_is_lru(monkeypatch) -> None:
    from app.core.config import settings
    from app.rag.retriever import HybridRetriever

    monkeypatch.setattr(settings, "BM25_CACHE_MAX_TENANTS", 2, raising=False)

    r = HybridRetriever()
    t1, t2, t3 = uuid4(), uuid4(), uuid4()

    r.upsert_bm25_documents([_doc("d1")], tenant_id=t1)
    r.upsert_bm25_documents([_doc("d2")], tenant_id=t2)

    # Touch t1 so t2 becomes the LRU.
    _ = r._search_bm25("content", tenant_id=t1)

    r.upsert_bm25_documents([_doc("d3")], tenant_id=t3)
    assert len(r._bm25_retrievers) == 2
    assert str(t2) not in r._bm25_retrievers
    assert str(t1) in r._bm25_retrievers
    assert str(t3) in r._bm25_retrievers

