from __future__ import annotations

import uuid
from uuid import UUID

import pytest
from langchain_core.documents import Document

from app.core.config import settings
from app.rag.retriever import HybridRetriever


def _mk_uuid(name: str) -> UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, name)


def test_sparse_retrieval_channel_scores_synonym_match(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    "SPLADE-style" sparse retrieval scaffold:
    - Query "kubernetes" should match a doc that only contains "k8s" when sparse retrieval is enabled.
    - BM25 is expected to have 0 overlap for this pair (kubernetes != k8s).

    This is a deterministic unit test with no external model downloads.
    """
    monkeypatch.setattr(settings, "LEXICAL_DB_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "BM25_INDEX_ENABLED", True, raising=False)

    # Feature flags under test.
    monkeypatch.setattr(settings, "SPARSE_RETRIEVAL_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "SPARSE_RETRIEVAL_PROVIDER", "deterministic", raising=False)
    # Minimal synonym mapping for the test (production SPLADE would learn this).
    monkeypatch.setattr(settings, "SPARSE_RETRIEVAL_SYNONYMS", "kubernetes:k8s", raising=False)

    tenant_id = _mk_uuid("tenant:sparse")
    dataset_id = _mk_uuid("dataset:sparse")

    doc_id = _mk_uuid("doc:sparse")
    d1_id = _mk_uuid("chunk:k8s")
    d2_id = _mk_uuid("chunk:noise")

    docs = [
        Document(
            page_content="k8s",
            id=str(d1_id),
            metadata={
                "tenant_id": str(tenant_id),
                "dataset_id": str(dataset_id),
                "document_id": str(doc_id),
                "chunk_index": 0,
                "chunk_id": str(d1_id),
                "doc_pipeline_key": f"{doc_id}:h",
                "pipeline_hash": "h",
                "source": "sparse.md",
            },
        ),
        Document(
            page_content="totally unrelated",
            id=str(d2_id),
            metadata={
                "tenant_id": str(tenant_id),
                "dataset_id": str(dataset_id),
                "document_id": str(doc_id),
                "chunk_index": 1,
                "chunk_id": str(d2_id),
                "doc_pipeline_key": f"{doc_id}:h",
                "pipeline_hash": "h",
                "source": "sparse.md",
            },
        ),
    ]

    retriever = HybridRetriever(tenant_id=tenant_id, dataset_id=dataset_id)
    retriever.upsert_bm25_documents(docs, tenant_id=tenant_id)

    results = retriever._hybrid_search(
        query="kubernetes",
        top_k=5,
        score_threshold=0.0,
        document_ids=None,
        tenant_id=tenant_id,
        retrieval_mode="keyword",
        metadata_filter=None,
    )

    by_id = {str(r.get("chunk_id")): r for r in results}
    assert str(d1_id) in by_id

    meta_1 = by_id[str(d1_id)].get("metadata") or {}
    meta_2 = by_id[str(d2_id)].get("metadata") or {}
    assert float(meta_1.get("sparse_score", 0.0) or 0.0) > 0.0
    assert float(meta_2.get("sparse_score", 0.0) or 0.0) == 0.0


def test_sparse_retrieval_can_be_enabled_per_retriever_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "LEXICAL_DB_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "BM25_INDEX_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "SPARSE_RETRIEVAL_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "SPARSE_RETRIEVAL_PROVIDER", "deterministic", raising=False)
    monkeypatch.setattr(settings, "SPARSE_RETRIEVAL_INDEX_PERSIST_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "SPARSE_RETRIEVAL_SYNONYMS", "kubernetes:k8s", raising=False)

    tenant_id = _mk_uuid("tenant:sparse-instance")
    dataset_id = _mk_uuid("dataset:sparse-instance")
    doc_id = _mk_uuid("doc:sparse-instance")
    chunk_id = _mk_uuid("chunk:sparse-instance")

    docs = [
        Document(
            page_content="k8s",
            id=str(chunk_id),
            metadata={
                "tenant_id": str(tenant_id),
                "dataset_id": str(dataset_id),
                "document_id": str(doc_id),
                "chunk_index": 0,
                "chunk_id": str(chunk_id),
                "doc_pipeline_key": f"{doc_id}:h",
                "pipeline_hash": "h",
                "source": "sparse.md",
            },
        )
    ]

    retriever = HybridRetriever(
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        sparse_enabled=True,
        sparse_provider="deterministic",
    )
    retriever.upsert_bm25_documents(docs, tenant_id=tenant_id)

    results = retriever._hybrid_search(
        query="kubernetes",
        top_k=5,
        score_threshold=0.0,
        document_ids=None,
        tenant_id=tenant_id,
        retrieval_mode="keyword",
        metadata_filter=None,
    )

    by_id = {str(r.get("chunk_id")): r for r in results}
    assert str(chunk_id) in by_id
    assert float(((by_id[str(chunk_id)].get("metadata") or {}).get("sparse_score") or 0.0)) > 0.0
