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


class _FakeSparseEncoder:
    def encode_batch(self, texts: list[str]):  # noqa: ANN001
        # Minimal sparse vectors: map both "kubernetes" and "k8s" to the same token.
        out = []
        for t in texts:
            raw = str(t or "").lower()
            if "kubernetes" in raw or "k8s" in raw:
                out.append({"k8s": 1.0})
            else:
                out.append({})
        return out


def test_sparse_retrieval_splade_provider_uses_persisted_index(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    When SPARSE_RETRIEVAL_PROVIDER=splade:
    - HybridRetriever should dispatch to the sparse encoder factory (no hard-coded deterministic-only path)
    - Sparse doc vectors should be persisted to disk and loadable without rebuilding

    This test uses a fake encoder to avoid any model downloads.
    """
    monkeypatch.setattr(settings, "LEXICAL_DB_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "BM25_INDEX_ENABLED", True, raising=False)

    monkeypatch.setattr(settings, "SPARSE_RETRIEVAL_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "SPARSE_RETRIEVAL_PROVIDER", "splade", raising=False)
    monkeypatch.setattr(settings, "SPARSE_RETRIEVAL_INDEX_PERSIST_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "SPARSE_RETRIEVAL_INDEX_DIR", str(tmp_path), raising=False)

    import app.rag.retrieval.sparse as sparse_mod

    monkeypatch.setattr(
        sparse_mod,
        "get_sparse_encoder",
        lambda **_kwargs: _FakeSparseEncoder(),
        raising=True,
    )

    tenant_id = _mk_uuid("tenant:splade")
    dataset_id = _mk_uuid("dataset:splade")
    doc_id = _mk_uuid("doc:splade")
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

    persisted = list(tmp_path.glob("*"))
    assert persisted, "expected sparse index to persist at least one file"

    # Clear in-memory sparse cache and verify search can load from persisted index
    # without triggering a rebuild.
    cache_key = retriever._bm25_scope_key(tenant_id=tenant_id, dataset_id=dataset_id, document_ids=None)
    retriever._sparse_doc_vectors.pop(cache_key, None)

    def _no_rebuild(**_kwargs):  # noqa: ANN001
        raise AssertionError("_build_sparse_index should not be called when persisted index exists")

    monkeypatch.setattr(retriever, "_build_sparse_index", _no_rebuild, raising=True)

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
    meta = by_id[str(d1_id)].get("metadata") or {}
    assert float(meta.get("sparse_score", 0.0) or 0.0) > 0.0

