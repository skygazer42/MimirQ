from __future__ import annotations

from uuid import uuid4

from langchain_core.documents import Document

from app.core.config import settings
from app.rag.retriever import HybridRetriever


def test_bm25_disabled_short_circuits_keyword_search(monkeypatch):  # noqa: ANN001
    tenant_id = uuid4()

    # Seed an in-memory BM25 cache first.
    monkeypatch.setattr(settings, "BM25_INDEX_ENABLED", True)
    retriever = HybridRetriever()
    retriever.upsert_bm25_documents(
        [
            Document(
                page_content="hello world",
                id=str(uuid4()),
                metadata={"tenant_id": str(tenant_id), "document_id": str(uuid4()), "chunk_index": 0},
            )
        ],
        tenant_id=tenant_id,
    )

    # Now disable BM25; keyword search must return empty even if cache exists.
    monkeypatch.setattr(settings, "BM25_INDEX_ENABLED", False)
    results = retriever._search_bm25(query="hello", top_k=5, tenant_id=tenant_id)
    assert results == []
    assert retriever._last_bm25_status["index_enabled"] is False
    assert retriever._last_bm25_status["reason"] == "index_disabled"
