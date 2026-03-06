from __future__ import annotations

import uuid
from uuid import UUID

import pytest
from langchain_core.documents import Document

from app.core.config import settings
from app.rag.retriever import HybridRetriever


def _mk_uuid(name: str) -> UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, name)


class _StubVectorStore:
    def search(self, **_kwargs):  # noqa: ANN001
        return []


def test_colbert_ann_respects_max_docs_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Resource bound: when the scope corpus exceeds COLBERT_RETRIEVAL_MAX_DOCS,
    the ColBERT ANN channel should skip (no index build) and remain bounded.
    """
    monkeypatch.setattr(settings, "LEXICAL_DB_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "BM25_INDEX_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "SPARSE_RETRIEVAL_ENABLED", False, raising=False)

    monkeypatch.setattr(settings, "COLBERT_RETRIEVAL_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "COLBERT_RETRIEVAL_PROVIDER", "deterministic", raising=False)
    monkeypatch.setattr(settings, "COLBERT_RETRIEVAL_INDEX_PERSIST_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "COLBERT_RETRIEVAL_MAX_DOCS", 1, raising=False)

    import app.rag.retriever as retriever_mod

    monkeypatch.setattr(retriever_mod, "get_vector_store", lambda: _StubVectorStore(), raising=True)

    tenant_id = _mk_uuid("tenant:colbert-guard")
    dataset_id = _mk_uuid("dataset:colbert-guard")
    doc_id = _mk_uuid("doc:colbert-guard")
    c1_id = _mk_uuid("chunk:1")
    c2_id = _mk_uuid("chunk:2")

    docs = [
        Document(
            page_content="alpha",
            id=str(c1_id),
            metadata={
                "tenant_id": str(tenant_id),
                "dataset_id": str(dataset_id),
                "document_id": str(doc_id),
                "chunk_index": 0,
                "chunk_id": str(c1_id),
                "doc_pipeline_key": f"{doc_id}:h",
                "pipeline_hash": "h",
                "source": "colbert.md",
            },
        ),
        Document(
            page_content="beta",
            id=str(c2_id),
            metadata={
                "tenant_id": str(tenant_id),
                "dataset_id": str(dataset_id),
                "document_id": str(doc_id),
                "chunk_index": 1,
                "chunk_id": str(c2_id),
                "doc_pipeline_key": f"{doc_id}:h",
                "pipeline_hash": "h",
                "source": "colbert.md",
            },
        ),
    ]

    retriever = HybridRetriever(tenant_id=tenant_id, dataset_id=dataset_id)
    retriever.upsert_bm25_documents(docs, tenant_id=tenant_id)

    def _no_build(**_kwargs):  # noqa: ANN001
        raise AssertionError("_build_colbert_index should not be called when max_docs guard triggers")

    monkeypatch.setattr(retriever, "_build_colbert_index", _no_build, raising=True)

    results = retriever._hybrid_search(
        query="alpha",
        top_k=5,
        score_threshold=0.0,
        document_ids=None,
        tenant_id=tenant_id,
        retrieval_mode="vector",
        metadata_filter=None,
    )
    assert results == []

    cm = retriever._last_channel_metrics or {}
    box = cm.get("colbert_ann") if isinstance(cm, dict) else None
    assert isinstance(box, dict)
    assert box.get("used") is True
    assert box.get("skipped_reason") == "too_many_docs"
    assert box.get("docs_n") == 2
    assert box.get("max_docs") == 1

