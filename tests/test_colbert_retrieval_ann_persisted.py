from __future__ import annotations

import uuid
from pathlib import Path
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


def test_colbert_ann_retrieval_builds_and_loads_persisted_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    ColBERT retrieval stack (ANN) should:
    - build an index on first use (deterministic provider for tests)
    - persist the index to disk
    - reload it when in-memory cache is cleared (without rebuilding)
    """
    monkeypatch.setattr(settings, "LEXICAL_DB_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "BM25_INDEX_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "SPARSE_RETRIEVAL_ENABLED", False, raising=False)

    monkeypatch.setattr(settings, "COLBERT_RETRIEVAL_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "COLBERT_RETRIEVAL_PROVIDER", "deterministic", raising=False)
    monkeypatch.setattr(settings, "COLBERT_RETRIEVAL_INDEX_PERSIST_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "COLBERT_RETRIEVAL_INDEX_DIR", str(tmp_path), raising=False)

    import app.rag.retriever as retriever_mod

    monkeypatch.setattr(retriever_mod, "get_vector_store", lambda: _StubVectorStore(), raising=True)

    tenant_id = _mk_uuid("tenant:colbert")
    dataset_id = _mk_uuid("dataset:colbert")
    doc_id = _mk_uuid("doc:colbert")
    d1_id = _mk_uuid("chunk:alpha")
    d2_id = _mk_uuid("chunk:beta")

    docs = [
        Document(
            page_content="alpha",
            id=str(d1_id),
            metadata={
                "tenant_id": str(tenant_id),
                "dataset_id": str(dataset_id),
                "document_id": str(doc_id),
                "chunk_index": 0,
                "chunk_id": str(d1_id),
                "doc_pipeline_key": f"{doc_id}:h",
                "pipeline_hash": "h",
                "source": "colbert.md",
            },
        ),
        Document(
            page_content="beta",
            id=str(d2_id),
            metadata={
                "tenant_id": str(tenant_id),
                "dataset_id": str(dataset_id),
                "document_id": str(doc_id),
                "chunk_index": 1,
                "chunk_id": str(d2_id),
                "doc_pipeline_key": f"{doc_id}:h",
                "pipeline_hash": "h",
                "source": "colbert.md",
            },
        ),
    ]

    retriever = HybridRetriever(tenant_id=tenant_id, dataset_id=dataset_id)
    retriever.upsert_bm25_documents(docs, tenant_id=tenant_id)

    results = retriever._hybrid_search(
        query="alpha",
        top_k=5,
        score_threshold=0.0,
        document_ids=None,
        tenant_id=tenant_id,
        retrieval_mode="vector",
        metadata_filter=None,
    )
    assert results
    top = results[0]
    assert str(top.get("chunk_id")) == str(d1_id)
    meta = top.get("metadata") or {}
    assert float(meta.get("colbert_score", 0.0) or 0.0) > 0.0

    assert list(tmp_path.glob("*")), "expected persisted colbert index artifacts"

    # Clear in-memory index cache and ensure the next search loads from disk (no rebuild).
    cache_key = retriever._bm25_scope_key(tenant_id=tenant_id, dataset_id=dataset_id, document_ids=None)
    if hasattr(retriever, "_colbert_index_cache"):
        retriever._colbert_index_cache.pop(cache_key, None)

    def _no_build(**_kwargs):  # noqa: ANN001
        raise AssertionError("_build_colbert_index should not be called when persisted index exists")

    if hasattr(retriever, "_build_colbert_index"):
        monkeypatch.setattr(retriever, "_build_colbert_index", _no_build, raising=True)

    results2 = retriever._hybrid_search(
        query="alpha",
        top_k=5,
        score_threshold=0.0,
        document_ids=None,
        tenant_id=tenant_id,
        retrieval_mode="vector",
        metadata_filter=None,
    )
    assert results2
    assert str(results2[0].get("chunk_id")) == str(d1_id)

