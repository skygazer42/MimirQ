from __future__ import annotations

import uuid

import numpy as np
import pytest
from langchain_core.documents import Document

from app.core.config import settings
from app.rag.retriever import HybridRetriever


def _mk_uuid(name: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, name)


class _StubVectorStore:
    def search(self, **_kwargs):  # noqa: ANN001
        return []


def test_sparse_index_incremental_upsert_encodes_only_new_docs(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Production goal (Wave2):
    - When BM25 docs are incrementally upserted, the sparse index update should be incremental too.
    - Specifically: only the newly upserted docs should be re-encoded, not the entire merged corpus.
    """
    monkeypatch.setattr(settings, "LEXICAL_DB_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "BM25_INDEX_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "SPARSE_RETRIEVAL_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "SPARSE_RETRIEVAL_PROVIDER", "splade", raising=False)
    # Keep test hermetic: do not write persisted indices to the workspace.
    monkeypatch.setattr(settings, "SPARSE_RETRIEVAL_INDEX_PERSIST_ENABLED", False, raising=False)

    import app.rag.retrieval.sparse as sparse_mod

    encode_calls: list[list[str]] = []

    class _FakeSparseEncoder:
        def encode_batch(self, texts: list[str]):  # noqa: ANN001
            encode_calls.append([str(t) for t in texts])
            return [{"t": 1.0} for _ in texts]

    fake = _FakeSparseEncoder()
    monkeypatch.setattr(sparse_mod, "get_sparse_encoder", lambda **_k: fake, raising=True)

    tenant_id = _mk_uuid("tenant:wave2:sparse")
    dataset_id = _mk_uuid("dataset:wave2:sparse")
    doc_id = _mk_uuid("doc:wave2:sparse")

    d1_id = _mk_uuid("chunk:wave2:alpha")
    d2_id = _mk_uuid("chunk:wave2:beta")

    d1 = Document(
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
            "source": "sparse.md",
        },
    )
    d2 = Document(
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
            "source": "sparse.md",
        },
    )

    retriever = HybridRetriever(tenant_id=tenant_id, dataset_id=dataset_id)
    retriever.upsert_bm25_documents([d1], tenant_id=tenant_id)
    retriever.upsert_bm25_documents([d2], tenant_id=tenant_id)

    assert encode_calls, "expected sparse encoder to be invoked"
    assert encode_calls[0] == ["alpha"]
    # Incremental requirement: second upsert encodes only the newly inserted doc.
    assert encode_calls[1] == ["beta"]


def test_bm25_upsert_infers_dataset_scope_from_document_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Ingestion uses the singleton hybrid_retriever without setting retriever.dataset_id.
    BM25 updates must still stay dataset-scoped when chunks carry dataset_id metadata;
    otherwise each ingested document rebuilds a growing tenant-wide BM25 corpus.
    """
    monkeypatch.setattr(settings, "SPARSE_RETRIEVAL_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "COLBERT_RETRIEVAL_ENABLED", False, raising=False)

    tenant_id = _mk_uuid("tenant:bm25:dataset-scope")
    dataset_id = _mk_uuid("dataset:bm25:dataset-scope")
    document_id = _mk_uuid("doc:bm25:dataset-scope")
    chunk_id = _mk_uuid("chunk:bm25:dataset-scope")
    retriever = HybridRetriever()

    retriever.upsert_bm25_documents(
        [
            Document(
                page_content="dataset scoped chunk",
                id=str(chunk_id),
                metadata={
                    "tenant_id": str(tenant_id),
                    "dataset_id": str(dataset_id),
                    "document_id": str(document_id),
                    "chunk_index": 0,
                    "chunk_id": str(chunk_id),
                },
            )
        ],
        tenant_id=tenant_id,
    )

    tenant_key = retriever._tenant_key(tenant_id)
    dataset_key = f"{tenant_key}:dataset:{dataset_id}"
    assert dataset_key in retriever._bm25_docs
    assert tenant_key not in retriever._bm25_docs


def test_bm25_upsert_defers_rebuild_when_dataset_scope_exceeds_eager_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Large corpus ingestion must not rebuild the whole dataset BM25 retriever after every document.
    Once the scope exceeds the eager limit, keep docs cached and defer retriever construction.
    """
    monkeypatch.setattr(settings, "BM25_EAGER_UPSERT_MAX_CHUNKS", 1, raising=False)
    monkeypatch.setattr(settings, "SPARSE_RETRIEVAL_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "COLBERT_RETRIEVAL_ENABLED", False, raising=False)

    tenant_id = _mk_uuid("tenant:bm25:eager-limit")
    dataset_id = _mk_uuid("dataset:bm25:eager-limit")
    document_id = _mk_uuid("doc:bm25:eager-limit")
    retriever = HybridRetriever(tenant_id=tenant_id, dataset_id=dataset_id)

    docs = [
        Document(
            page_content="alpha",
            id=str(_mk_uuid("chunk:bm25:eager-limit:alpha")),
            metadata={"tenant_id": str(tenant_id), "dataset_id": str(dataset_id), "document_id": str(document_id), "chunk_index": 0},
        ),
        Document(
            page_content="beta",
            id=str(_mk_uuid("chunk:bm25:eager-limit:beta")),
            metadata={"tenant_id": str(tenant_id), "dataset_id": str(dataset_id), "document_id": str(document_id), "chunk_index": 1},
        ),
    ]

    retriever.upsert_bm25_documents(docs, tenant_id=tenant_id)

    cache_key = f"{retriever._tenant_key(tenant_id)}:dataset:{dataset_id}"
    assert len(retriever._bm25_docs[cache_key]) == 2
    assert cache_key not in retriever._bm25_retrievers
    assert retriever._chunk_id_lookup[cache_key]


def test_colbert_ann_incremental_upsert_encodes_only_new_docs(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Production goal (Wave2):
    - When a ColBERT ANN index already exists, incremental BM25 upserts should update the ANN index
      by embedding only the new documents (not rebuilding/embedding the entire corpus).
    """
    monkeypatch.setattr(settings, "LEXICAL_DB_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "BM25_INDEX_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "SPARSE_RETRIEVAL_ENABLED", False, raising=False)

    monkeypatch.setattr(settings, "COLBERT_RETRIEVAL_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "COLBERT_RETRIEVAL_PROVIDER", "hf", raising=False)
    # Keep test hermetic: do not write persisted indices to the workspace.
    monkeypatch.setattr(settings, "COLBERT_RETRIEVAL_INDEX_PERSIST_ENABLED", False, raising=False)

    import app.rag.retriever as retriever_mod

    monkeypatch.setattr(retriever_mod, "get_vector_store", lambda: _StubVectorStore(), raising=True)

    import app.rag.retrieval.colbert_ann as colbert_mod

    embed_calls: list[list[str]] = []

    class _FakeEmbedder:
        def encode_batch(self, texts: list[str]) -> np.ndarray:  # noqa: ANN001
            embed_calls.append([str(t) for t in texts])
            dim = 8
            out = np.zeros((len(texts), dim), dtype=np.float32)
            for i, t in enumerate(texts):
                out[i, 0] = float(len(str(t or "")))
            return out

    monkeypatch.setattr(colbert_mod, "get_dense_embedder", lambda **_k: _FakeEmbedder(), raising=True)

    tenant_id = _mk_uuid("tenant:wave2:colbert")
    dataset_id = _mk_uuid("dataset:wave2:colbert")
    doc_id = _mk_uuid("doc:wave2:colbert")

    d1_id = _mk_uuid("chunk:wave2:colbert:alpha")
    d2_id = _mk_uuid("chunk:wave2:colbert:beta")
    d3_id = _mk_uuid("chunk:wave2:colbert:gamma")

    d1 = Document(
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
    )
    d2 = Document(
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
    )
    d3 = Document(
        page_content="gamma",
        id=str(d3_id),
        metadata={
            "tenant_id": str(tenant_id),
            "dataset_id": str(dataset_id),
            "document_id": str(doc_id),
            "chunk_index": 2,
            "chunk_id": str(d3_id),
            "doc_pipeline_key": f"{doc_id}:h",
            "pipeline_hash": "h",
            "source": "colbert.md",
        },
    )

    retriever = HybridRetriever(tenant_id=tenant_id, dataset_id=dataset_id)
    retriever.upsert_bm25_documents([d1, d2], tenant_id=tenant_id)

    # Build the initial ANN index via a retrieval call (vector backend returns empty).
    _ = retriever._hybrid_search(
        query="alpha",
        top_k=5,
        score_threshold=0.0,
        document_ids=None,
        tenant_id=tenant_id,
        retrieval_mode="vector",
        metadata_filter=None,
    )

    # Incremental upsert: update index with only the new doc.
    retriever.upsert_bm25_documents([d3], tenant_id=tenant_id)

    # The last embedder call should be for the newly upserted chunk only.
    assert embed_calls, "expected colbert embedder to be invoked"
    assert embed_calls[-1] == ["gamma"]


def test_remove_from_bm25_index_by_metadata_filter_updates_sparse_index(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Production goal (Wave2):
    - Scoped deletions (e.g. deleting a doc_pipeline_key version) must keep optional candidate indexes
      in sync, otherwise sparse retrieval can return false negatives / stale hits.
    """
    monkeypatch.setattr(settings, "LEXICAL_DB_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "BM25_INDEX_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "SPARSE_RETRIEVAL_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "SPARSE_RETRIEVAL_PROVIDER", "deterministic", raising=False)
    monkeypatch.setattr(settings, "SPARSE_RETRIEVAL_INDEX_PERSIST_ENABLED", False, raising=False)

    tenant_id = _mk_uuid("tenant:wave2:sparse:delete")
    doc1_id = _mk_uuid("doc:wave2:sparse:delete:1")
    doc2_id = _mk_uuid("doc:wave2:sparse:delete:2")

    c1_id = _mk_uuid("chunk:wave2:sparse:delete:c1")
    c2_id = _mk_uuid("chunk:wave2:sparse:delete:c2")

    docs = [
        Document(
            page_content="alpha",
            id=str(c1_id),
            metadata={
                "tenant_id": str(tenant_id),
                "document_id": str(doc1_id),
                "chunk_index": 0,
                "chunk_id": str(c1_id),
                "doc_pipeline_key": f"{doc1_id}:h1",
                "pipeline_hash": "h1",
                "source": "sparse.md",
            },
        ),
        Document(
            page_content="beta",
            id=str(c2_id),
            metadata={
                "tenant_id": str(tenant_id),
                "document_id": str(doc2_id),
                "chunk_index": 0,
                "chunk_id": str(c2_id),
                "doc_pipeline_key": f"{doc2_id}:h2",
                "pipeline_hash": "h2",
                "source": "sparse.md",
            },
        ),
    ]

    retriever = HybridRetriever(tenant_id=tenant_id, dataset_id=None)
    retriever.upsert_bm25_documents(docs, tenant_id=tenant_id)

    cache_key = retriever._bm25_scope_key(tenant_id=tenant_id, dataset_id=None, document_ids=None)
    assert str(c1_id) in (retriever._sparse_doc_vectors.get(cache_key) or {})
    assert str(c2_id) in (retriever._sparse_doc_vectors.get(cache_key) or {})

    removed = retriever.remove_from_bm25_index_by_metadata_filter(
        tenant_id=tenant_id,
        metadata_filter={"doc_pipeline_key": {"$eq": f"{doc1_id}:h1"}},
    )
    assert removed >= 1
    assert str(c1_id) not in (retriever._sparse_doc_vectors.get(cache_key) or {})
    assert str(c2_id) in (retriever._sparse_doc_vectors.get(cache_key) or {})
