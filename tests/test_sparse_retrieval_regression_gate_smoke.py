from __future__ import annotations

import uuid
from uuid import UUID

import pytest
from langchain_core.documents import Document

from app.core.config import settings
from app.rag.evaluation.evidence_retrieve_gate import compute_retrieval_item_meta
from app.rag.retriever import HybridRetriever


def _mk_uuid(name: str) -> UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, name)


class _FakeSpladeEncoder:
    """
    Tiny fake encoder to validate sparse(SPLADE) plumbing without model downloads.

    Behavior:
    - Query ("QUERY:...") -> emits {"match": 1.0}
    - Reference docs ("kubernetes") -> emits {"match": 1.0}
    - Distractor docs -> emits {}
    """

    def encode_batch(self, texts: list[str]):  # noqa: ANN001
        out = []
        for t in texts:
            raw = str(t or "").strip().lower()
            if "query:" in raw:
                out.append({"match": 1.0})
                continue
            if "kubernetes" in raw:
                out.append({"match": 1.0})
                continue
            out.append({})
        return out


def test_sparse_splade_channel_improves_retrieval_gate_hit(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Smoke-test: sparse retrieval should be feature-flagged and regression-evaluable.

    We construct a case where BM25 alone cannot retrieve the reference chunk within top_k,
    but enabling sparse(SPLADE provider path, using a fake encoder) makes Hit@K succeed.
    """
    monkeypatch.setattr(settings, "LEXICAL_DB_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "BM25_INDEX_ENABLED", True, raising=False)

    # Sparse index persistence is irrelevant for this unit test; keep it off to avoid FS writes.
    monkeypatch.setattr(settings, "SPARSE_RETRIEVAL_INDEX_PERSIST_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "SPARSE_RETRIEVAL_PROVIDER", "splade", raising=False)

    import app.rag.retrieval.sparse as sparse_mod

    monkeypatch.setattr(
        sparse_mod,
        "get_sparse_encoder",
        lambda **_kwargs: _FakeSpladeEncoder(),
        raising=True,
    )

    tenant_id = _mk_uuid("tenant:sparse-regression")
    dataset_id = _mk_uuid("dataset:sparse-regression")

    # Reference chunk: does not contain the BM25 query token "k8s".
    ref_doc_id = _mk_uuid("doc:reference")
    ref_chunk_id = _mk_uuid("chunk:reference")

    docs: list[Document] = [
        Document(
            page_content="Kubernetes is a container orchestration system.",
            id=str(ref_chunk_id),
            metadata={
                "tenant_id": str(tenant_id),
                "dataset_id": str(dataset_id),
                "document_id": str(ref_doc_id),
                "chunk_index": 0,
                "chunk_id": str(ref_chunk_id),
                "doc_pipeline_key": f"{ref_doc_id}:h",
                "pipeline_hash": "h",
                "source": "ref.md",
            },
        )
    ]

    # Distractors: match BM25 query token "k8s" and will fill up fetch_k so the reference
    # chunk is not returned unless sparse is enabled.
    for i in range(0, 30):
        did = _mk_uuid(f"doc:distractor:{i}")
        cid = _mk_uuid(f"chunk:distractor:{i}")
        docs.append(
            Document(
                page_content=f"k8s is mentioned here ({i}).",
                id=str(cid),
                metadata={
                    "tenant_id": str(tenant_id),
                    "dataset_id": str(dataset_id),
                    "document_id": str(did),
                    "chunk_index": 0,
                    "chunk_id": str(cid),
                    "doc_pipeline_key": f"{did}:h",
                    "pipeline_hash": "h",
                    "source": "noise.md",
                },
            )
        )

    retriever = HybridRetriever(tenant_id=tenant_id, dataset_id=dataset_id)
    # Keep the test deterministic and avoid post-fusion trimming effects.
    retriever.dedup_enabled = False
    retriever.max_chunks_per_doc = 10_000
    retriever.enable_reranker = False

    # Ensure sparse can enforce recall in the visible prefix when enabled.
    retriever.fusion_strategy = "budgeted_rrf"
    retriever.fusion_budgets = {"vector": 0, "bm25": 4, "lexical": 0, "sparse": 1}

    retriever.upsert_bm25_documents(docs, tenant_id=tenant_id)

    top_k = 5
    query = "QUERY:k8s"

    case = {
        "question": query,
        "reference_sources": [{"chunk_id": str(ref_chunk_id)}],
    }

    # 1) Sparse disabled -> reference is not retrieved in top_k.
    monkeypatch.setattr(settings, "SPARSE_RETRIEVAL_ENABLED", False, raising=False)
    out_off = retriever._hybrid_search(
        query=query,
        top_k=top_k,
        score_threshold=0.0,
        document_ids=None,
        tenant_id=tenant_id,
        retrieval_mode="keyword",
        enable_weight_rerank=False,
        metadata_filter=None,
    )
    meta_off = compute_retrieval_item_meta(case=case, citations=out_off)
    assert meta_off["retrieval_hit_at_5"] is False

    # 2) Sparse enabled -> reference is retrieved in top_k.
    monkeypatch.setattr(settings, "SPARSE_RETRIEVAL_ENABLED", True, raising=False)
    out_on = retriever._hybrid_search(
        query=query,
        top_k=top_k,
        score_threshold=0.0,
        document_ids=None,
        tenant_id=tenant_id,
        retrieval_mode="keyword",
        enable_weight_rerank=False,
        metadata_filter=None,
    )
    meta_on = compute_retrieval_item_meta(case=case, citations=out_on)
    assert meta_on["retrieval_hit_at_5"] is True
