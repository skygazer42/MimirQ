from __future__ import annotations

from uuid import uuid4

import pytest
from langchain_core.documents import Document

from app.core.config import settings
from app.rag.retriever import HybridRetriever


def test_bm25_retrieves_chunk_via_document_questions_and_keeps_original_content(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "BM25_INDEX_ENABLED", True, raising=False)

    tenant_id = uuid4()
    document_id = uuid4()
    chunk_id = uuid4()
    distractor_document_id = uuid4()
    distractor_chunk_id = uuid4()

    retriever = HybridRetriever()
    retriever.upsert_bm25_documents(
        [
            Document(
                page_content="This section describes general panel maintenance notes.",
                id=str(distractor_chunk_id),
                metadata={
                    "tenant_id": str(tenant_id),
                    "document_id": str(distractor_document_id),
                    "chunk_index": 0,
                    "chunk_id": str(distractor_chunk_id),
                    "source": "plain.md",
                },
            ),
            Document(
                page_content="This section describes general panel maintenance notes.",
                id=str(chunk_id),
                metadata={
                    "tenant_id": str(tenant_id),
                    "document_id": str(document_id),
                    "chunk_index": 0,
                    "chunk_id": str(chunk_id),
                    "source": "guide.md",
                    "document_questions": [
                        "How do I configure the MQTT broker keepalive setting?",
                    ],
                },
            )
        ],
        tenant_id=tenant_id,
    )

    results = retriever._search_bm25(
        query="MQTT broker keepalive",
        top_k=5,
        tenant_id=tenant_id,
    )

    assert results, "expected document_questions to participate in BM25 retrieval"
    assert str(results[0].get("chunk_id")) == str(chunk_id)
    assert results[0].get("content") == "This section describes general panel maintenance notes."


def test_sparse_retrieves_chunk_via_document_questions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "BM25_INDEX_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "SPARSE_RETRIEVAL_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "SPARSE_RETRIEVAL_PROVIDER", "deterministic", raising=False)
    monkeypatch.setattr(settings, "SPARSE_RETRIEVAL_INDEX_PERSIST_ENABLED", False, raising=False)

    tenant_id = uuid4()
    dataset_id = uuid4()
    document_id = uuid4()
    chunk_id = uuid4()

    retriever = HybridRetriever(tenant_id=tenant_id, dataset_id=dataset_id)
    retriever.upsert_bm25_documents(
        [
            Document(
                page_content="This section only lists routine maintenance windows.",
                id=str(chunk_id),
                metadata={
                    "tenant_id": str(tenant_id),
                    "dataset_id": str(dataset_id),
                    "document_id": str(document_id),
                    "chunk_index": 0,
                    "chunk_id": str(chunk_id),
                    "source": "ops.md",
                    "document_questions": [
                        "How do I configure the MQTT broker keepalive setting?",
                    ],
                },
            )
        ],
        tenant_id=tenant_id,
    )

    results = retriever._search_sparse(
        query="MQTT broker keepalive",
        top_k=3,
        tenant_id=tenant_id,
    )

    assert results, "expected document_questions to participate in sparse retrieval"
    assert str(results[0].get("chunk_id")) == str(chunk_id)
