from __future__ import annotations

import uuid
from uuid import UUID

import pytest
from langchain_core.documents import Document

from app.core.config import settings
from app.rag.retriever import HybridRetriever


def _mk_uuid(name: str) -> UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, name)


def _build_docs(*, tenant_id: UUID, dataset_id: UUID, doc_id: UUID, chunk_id: UUID) -> list[Document]:
    return [
        Document(
            page_content="kubernetes rollout uses kubectl apply",
            id=str(chunk_id),
            metadata={
                "tenant_id": str(tenant_id),
                "dataset_id": str(dataset_id),
                "document_id": str(doc_id),
                "chunk_index": 0,
                "chunk_id": str(chunk_id),
                "doc_pipeline_key": f"{doc_id}:h",
                "pipeline_hash": "h",
                "source": "sparse-status.md",
            },
        )
    ]


def test_hybrid_search_exposes_sparse_provider_status_with_invalid_provider_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "LEXICAL_DB_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "BM25_INDEX_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "SPARSE_RETRIEVAL_INDEX_PERSIST_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "SPARSE_SPLADE_MODEL_NAME", "", raising=False)

    import app.rag.retrieval.sparse_prometheus_metrics as sparse_metrics_mod

    observed: list[dict] = []
    monkeypatch.setattr(
        sparse_metrics_mod,
        "observe_sparse_search",
        lambda **kwargs: observed.append(dict(kwargs)),
        raising=True,
    )

    tenant_id = _mk_uuid("tenant:sparse-status:invalid")
    dataset_id = _mk_uuid("dataset:sparse-status:invalid")
    doc_id = _mk_uuid("doc:sparse-status:invalid")
    chunk_id = _mk_uuid("chunk:sparse-status:invalid")
    docs = _build_docs(tenant_id=tenant_id, dataset_id=dataset_id, doc_id=doc_id, chunk_id=chunk_id)

    retriever = HybridRetriever(
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        sparse_enabled=True,
        sparse_provider="invalid-provider",
    )
    retriever.upsert_bm25_documents(docs, tenant_id=tenant_id)

    out = retriever._hybrid_search(
        query="kubernetes",
        top_k=5,
        score_threshold=0.0,
        document_ids=None,
        tenant_id=tenant_id,
        retrieval_mode="keyword",
        metadata_filter=None,
    )

    assert out
    sparse_box = (retriever._last_channel_metrics or {}).get("sparse") or {}
    provider_status = sparse_box.get("provider_status") or {}
    assert provider_status.get("status") == "fallback"
    assert provider_status.get("reason") == "provider_invalid"
    assert provider_status.get("requested_provider") == "invalid-provider"
    assert provider_status.get("effective_provider") == "deterministic"
    assert provider_status.get("provider_supported") is False

    assert observed
    assert observed[-1].get("reason") == "provider_invalid"


def test_sparse_search_reports_scope_empty_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "SPARSE_RETRIEVAL_INDEX_PERSIST_ENABLED", False, raising=False)

    import app.rag.retrieval.sparse_prometheus_metrics as sparse_metrics_mod

    observed: list[dict] = []
    monkeypatch.setattr(
        sparse_metrics_mod,
        "observe_sparse_search",
        lambda **kwargs: observed.append(dict(kwargs)),
        raising=True,
    )

    tenant_id = _mk_uuid("tenant:sparse-status:empty")
    retriever = HybridRetriever(
        tenant_id=tenant_id,
        dataset_id=None,
        sparse_enabled=True,
        sparse_provider="deterministic",
    )

    rows = retriever._search_sparse(
        query="kubernetes",
        top_k=5,
        document_ids=None,
        tenant_id=tenant_id,
        metadata_filter=None,
    )
    assert rows == []
    assert observed
    assert observed[-1].get("outcome") == "skipped"
    assert observed[-1].get("reason") == "scope_empty"


def test_orchestrator_trace_contains_sparse_provider_status_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.retrieval.orchestrator as orch_mod

    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_MULTI_QUERY", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_HYDE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_QUERY_DECOMPOSITION", False, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_QUERY_PARALLELISM", 1, raising=False)
    monkeypatch.setattr(settings, "KG_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "KG_CHAT_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_CHUNK_INJECTION_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_QUERY_EXPANSION_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "LEXICAL_DB_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "SPARSE_RETRIEVAL_INDEX_PERSIST_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "SPARSE_SPLADE_MODEL_NAME", "", raising=False)

    tenant_id = _mk_uuid("tenant:sparse-trace")
    dataset_id = _mk_uuid("dataset:sparse-trace")
    doc_id = _mk_uuid("doc:sparse-trace")
    chunk_id = _mk_uuid("chunk:sparse-trace")
    docs = _build_docs(tenant_id=tenant_id, dataset_id=dataset_id, doc_id=doc_id, chunk_id=chunk_id)

    retriever = HybridRetriever(
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        sparse_enabled=True,
        sparse_provider="invalid-provider",
    )
    retriever.upsert_bm25_documents(docs, tenant_id=tenant_id)
    monkeypatch.setattr(orch_mod, "hybrid_retriever", retriever, raising=True)

    out = orch_mod.run_retrieval(
        {
            "question": "kubernetes",
            "history": [],
            "tenant_id": str(tenant_id),
            "account_id": "u",
            "dataset_id": str(dataset_id),
            "document_ids": None,
            "top_k": 5,
            "retrieval_mode": "keyword",
            "sparse_retrieval_enabled": True,
            "sparse_retrieval_provider": "invalid-provider",
            "metrics": {},
        }
    )

    per_query = (((out.get("retrieval_trace") or {}).get("retrieval") or {}).get("per_query") or [])
    assert per_query
    sparse_box = ((((per_query[0] or {}).get("retriever_debug") or {}).get("channels") or {}).get("sparse") or {})
    provider_status = sparse_box.get("provider_status") or {}
    assert provider_status.get("status") == "fallback"
    assert provider_status.get("reason") == "provider_invalid"
    assert provider_status.get("effective_provider") == "deterministic"
