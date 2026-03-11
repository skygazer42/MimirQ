from __future__ import annotations

import uuid
from pathlib import Path
from uuid import UUID

import pytest
from langchain_core.documents import Document

from app.core.config import settings
from app.rag.retrieval.sparse import SparseIndexStore, SparseVector
from app.rag.retriever import HybridRetriever


def _mk_uuid(name: str) -> UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, name)


def test_sparse_index_store_requires_matching_corpus_fingerprint(tmp_path: Path) -> None:
    store = SparseIndexStore(base_dir=str(tmp_path))
    provider_config = {"provider": "deterministic", "synonyms_raw": "kubernetes:k8s"}

    store.save(
        cache_key="scope-a",
        provider_config=provider_config,
        corpus_fingerprint="fp-a",
        vectors={"chunk-a": SparseVector(weights={"k8s": 1.0})},
    )

    hit = store.load(
        cache_key="scope-a",
        provider_config=provider_config,
        expected_fingerprint="fp-a",
    )
    miss = store.load(
        cache_key="scope-a",
        provider_config=provider_config,
        expected_fingerprint="fp-b",
    )

    assert hit is not None
    assert "chunk-a" in hit
    assert miss is None


def test_sparse_retrieval_reuses_persisted_index_without_full_rebuild(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(settings, "LEXICAL_DB_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "BM25_INDEX_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "SPARSE_RETRIEVAL_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "SPARSE_RETRIEVAL_PROVIDER", "deterministic", raising=False)
    monkeypatch.setattr(settings, "SPARSE_RETRIEVAL_SYNONYMS", "kubernetes:k8s", raising=False)
    monkeypatch.setattr(settings, "SPARSE_RETRIEVAL_INDEX_PERSIST_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "SPARSE_RETRIEVAL_INDEX_DIR", str(tmp_path), raising=False)

    tenant_id = _mk_uuid("tenant:sparse-persist")
    dataset_id = _mk_uuid("dataset:sparse-persist")
    document_id = _mk_uuid("doc:sparse-persist")
    chunk_id = _mk_uuid("chunk:sparse-persist")

    docs = [
        Document(
            page_content="k8s rollout",
            id=str(chunk_id),
            metadata={
                "tenant_id": str(tenant_id),
                "dataset_id": str(dataset_id),
                "document_id": str(document_id),
                "chunk_index": 0,
                "chunk_id": str(chunk_id),
                "doc_pipeline_key": f"{document_id}:h",
                "pipeline_hash": "h",
                "source": "sparse-persist.md",
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

    persisted = list(Path(tmp_path).glob("deterministic/index_*.json.gz"))
    assert persisted, "Expected sparse index artifacts to be persisted to disk"

    cache_key = retriever._bm25_scope_key(tenant_id=tenant_id, dataset_id=dataset_id, document_ids=None)
    retriever._sparse_doc_vectors.pop(cache_key, None)

    def _unexpected_full_rebuild(*_args, **_kwargs) -> None:
        raise AssertionError("Sparse full rebuild should not run when persisted index is reusable")

    monkeypatch.setattr(retriever, "_build_sparse_index", _unexpected_full_rebuild, raising=True)

    hits = retriever._search_sparse(
        query="kubernetes",
        top_k=5,
        document_ids=None,
        tenant_id=tenant_id,
        metadata_filter=None,
    )

    by_id = {str(row.get("chunk_id")): row for row in hits}
    assert str(chunk_id) in by_id
    meta = by_id[str(chunk_id)].get("metadata") or {}
    assert float(meta.get("sparse_score") or 0.0) > 0.0
