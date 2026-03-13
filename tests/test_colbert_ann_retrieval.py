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


def test_colbert_ann_provider_capability_marks_hf_model_missing() -> None:
    from app.rag.retrieval.colbert_ann import resolve_colbert_ann_provider_capability

    status = resolve_colbert_ann_provider_capability(
        colbert_enabled=True,
        requested_provider="hf",
        model_name="",
        device="cpu",
        docs_count=10,
        max_docs=1000,
    )

    assert status.get("status") == "fallback"
    assert status.get("reason") == "hf_model_missing"
    assert status.get("effective_provider") == "deterministic"
    assert status.get("ready") is True


def test_hybrid_search_exposes_colbert_readiness_diagnostics_for_hf_missing_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "COLBERT_RETRIEVAL_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "COLBERT_RETRIEVAL_PROVIDER", "hf", raising=False)
    monkeypatch.setattr(settings, "COLBERT_RETRIEVAL_MODEL_NAME", "", raising=False)
    monkeypatch.setattr(settings, "COLBERT_RETRIEVAL_INDEX_PERSIST_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "COLBERT_RETRIEVAL_MAX_DOCS", 1000, raising=False)
    monkeypatch.setattr(settings, "BM25_INDEX_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "LEXICAL_DB_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "SPARSE_RETRIEVAL_ENABLED", False, raising=False)

    import app.rag.retriever as retriever_mod

    monkeypatch.setattr(retriever_mod, "get_vector_store", lambda: _StubVectorStore(), raising=True)

    tenant_id = _mk_uuid("tenant:colbert-readiness")
    dataset_id = _mk_uuid("dataset:colbert-readiness")
    doc_id = _mk_uuid("doc:colbert-readiness")
    chunk_id = _mk_uuid("chunk:colbert-readiness")

    docs = [
        Document(
            page_content="kubernetes rollout with kubectl",
            id=str(chunk_id),
            metadata={
                "tenant_id": str(tenant_id),
                "dataset_id": str(dataset_id),
                "document_id": str(doc_id),
                "chunk_index": 0,
                "chunk_id": str(chunk_id),
                "doc_pipeline_key": f"{doc_id}:h",
                "pipeline_hash": "h",
                "source": "colbert-readiness.md",
            },
        )
    ]

    retriever = HybridRetriever(tenant_id=tenant_id, dataset_id=dataset_id)
    retriever.upsert_bm25_documents(docs, tenant_id=tenant_id)

    out = retriever._hybrid_search(
        query="kubernetes",
        top_k=5,
        score_threshold=0.0,
        document_ids=None,
        tenant_id=tenant_id,
        retrieval_mode="vector",
        metadata_filter=None,
    )

    assert isinstance(out, list)
    box = ((retriever._last_channel_metrics or {}).get("colbert_ann") or {})
    readiness = box.get("readiness") or {}
    assert readiness.get("status") == "fallback"
    assert readiness.get("reason") == "hf_model_missing"
    assert readiness.get("effective_provider") == "deterministic"
