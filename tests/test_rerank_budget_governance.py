from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import pytest
from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.documents import Document

from app.core.config import settings
from app.rag.reranker.base import BaseReranker
from app.rag.reranker.types import RerankCandidate, RerankResult
from app.rag.retriever import HybridRetriever


class _StubVectorStore:
    def __init__(self, *, results):  # noqa: ANN001
        self._results = list(results)

    def search(self, **_kwargs):  # noqa: ANN003
        return list(self._results)


@dataclass
class _BudgetAssertingReranker(BaseReranker):
    expected_top_n: int

    def rerank(self, query: str, candidates: Sequence[RerankCandidate], **kwargs: Any) -> RerankResult:  # noqa: ARG002
        top_n = int(kwargs.get("top_n") or 0)
        assert top_n == int(self.expected_top_n)
        ordered = [str(c.id) for c in candidates]
        score_map = {cid: float(len(ordered) - i) for i, cid in enumerate(ordered)}
        return RerankResult(ordered_ids=ordered, score_map=score_map, provider="stub", model_used="stub")


def test_retriever_rerank_budget_uses_requested_k_not_search_k(monkeypatch: pytest.MonkeyPatch) -> None:
    retriever = HybridRetriever()
    retriever.k = 5
    retriever.tenant_id = uuid4()
    retriever.dataset_id = uuid4()
    retriever.account_id = "u"
    retriever.retrieval_mode = "vector"

    retriever.enable_reranker = True
    retriever.reranker_provider = "stub"
    retriever.reranker_top_n = 5

    # Force overfetch so search_k > requested_k (this used to inflate rerank budget incorrectly).
    monkeypatch.setattr(settings, "RETRIEVAL_OVERFETCH_MULTIPLIER", 4, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_OVERFETCH_MAX_K", 0, raising=False)

    # Keep unit-level: no Postgres lexical channel or enrichment.
    monkeypatch.setattr(settings, "LEXICAL_DB_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "BM25_INDEX_ENABLED", False, raising=False)

    vector_candidates = []
    ds_id = str(retriever.dataset_id)
    for i in range(40):
        vector_candidates.append(
            {
                "chunk_id": str(uuid4()),
                "content": f"vector hit {i}",
                # Dataset scope is pushed down via metadata_filter; include it so vector results survive
                # the client-side safety filter in HybridRetriever._hybrid_search.
                "metadata": {"document_id": str(uuid4()), "dataset_id": ds_id, "chunk_index": i},
                "score": 0.9,
            }
        )

    stub_store = _StubVectorStore(results=vector_candidates)
    monkeypatch.setattr("app.storage.vector.factory.get_vector_store", lambda: stub_store, raising=True)
    monkeypatch.setattr("app.rag.retriever.get_vector_store", lambda: stub_store, raising=False)

    monkeypatch.setattr(HybridRetriever, "_enrich_results_with_db_metadata", lambda _self, r, **_k: r, raising=True)
    monkeypatch.setattr(HybridRetriever, "_expand_results_with_neighbors", lambda _self, r: r, raising=True)
    monkeypatch.setattr(HybridRetriever, "_auto_merge_parent_child", lambda _self, r: r, raising=True)

    monkeypatch.setattr(
        "app.rag.retriever.get_reranker",
        lambda _provider: _BudgetAssertingReranker(expected_top_n=5),
        raising=True,
    )

    retriever._get_relevant_documents(
        "q",
        run_manager=CallbackManagerForRetrieverRun.get_noop_manager(),
    )

    channels = (retriever._last_debug_metrics or {}).get("channels") or {}
    rerank = channels.get("rerank") or {}
    assert isinstance(rerank, dict)
    assert rerank.get("candidates_n") == 5


class _FakeRetriever:
    def __init__(self, *, docs: list[Document]) -> None:
        self._docs = list(docs)
        self._last_debug_metrics: dict = {}

    def model_copy(self, **_kwargs):  # noqa: ANN001, ANN002, ANN003
        return self

    def invoke(self, _q: str):  # noqa: ANN001
        return list(self._docs)


def test_orchestrator_post_rerank_trace_includes_skip_reason_on_provider_off(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.retrieval.orchestrator as orch_mod

    # Deterministic: no LLM-dependent query transforms.
    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_MULTI_QUERY", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_HYDE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_QUERY_DECOMPOSITION", False, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_QUERY_PARALLELISM", 1, raising=False)

    # Avoid KG work.
    monkeypatch.setattr(settings, "KG_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "KG_CHAT_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_CHUNK_INJECTION_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_QUERY_EXPANSION_ENABLED", False, raising=False)

    # Enable post-rerank but set provider off.
    monkeypatch.setattr(settings, "EVIDENCE_POST_RERANK_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "EVIDENCE_POST_RERANK_PROVIDER", "off", raising=False)

    doc_id = "doc"
    d1 = Document(page_content="a", id="a", metadata={"document_id": doc_id, "chunk_id": "a", "score": 0.1})
    monkeypatch.setattr(orch_mod, "hybrid_retriever", _FakeRetriever(docs=[d1]), raising=True)

    out = orch_mod.run_retrieval(
        {
            "question": "should-not-leak",
            "history": [],
            "tenant_id": "t",
            "account_id": "u",
            "dataset_id": None,
            "document_ids": [doc_id],
            "top_k": 1,
            "retrieval_mode": "vector",
            "metrics": {},
        }
    )

    trace = out.get("retrieval_trace") or {}
    post = (trace.get("post_rerank") or {})
    assert post.get("enabled") is True
    assert post.get("used") is False
    assert post.get("skip_reason") == "provider_off"

    dumped = json.dumps(trace, ensure_ascii=False)
    assert "should-not-leak" not in dumped


def test_orchestrator_post_rerank_trace_reports_error_without_breaking_retrieval(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.retrieval.orchestrator as orch_mod

    # Deterministic: no LLM-dependent query transforms.
    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_MULTI_QUERY", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_HYDE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_QUERY_DECOMPOSITION", False, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_QUERY_PARALLELISM", 1, raising=False)

    # Avoid KG work.
    monkeypatch.setattr(settings, "KG_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "KG_CHAT_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_CHUNK_INJECTION_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_QUERY_EXPANSION_ENABLED", False, raising=False)

    # Enable post-rerank and use a stub provider that errors.
    monkeypatch.setattr(settings, "EVIDENCE_POST_RERANK_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "EVIDENCE_POST_RERANK_PROVIDER", "stub", raising=False)
    monkeypatch.setattr(settings, "EVIDENCE_POST_RERANK_TOP_N", 5, raising=False)

    def _boom(_provider: str, **_kwargs):  # noqa: ANN001
        raise RuntimeError("rerank down")

    monkeypatch.setattr(orch_mod, "get_reranker", _boom, raising=True)

    doc_id = "doc"
    d1 = Document(page_content="a", id="a", metadata={"document_id": doc_id, "chunk_id": "a", "score": 0.1})
    monkeypatch.setattr(orch_mod, "hybrid_retriever", _FakeRetriever(docs=[d1]), raising=True)

    out = orch_mod.run_retrieval(
        {
            "question": "should-not-leak",
            "history": [],
            "tenant_id": "t",
            "account_id": "u",
            "dataset_id": None,
            "document_ids": [doc_id],
            "top_k": 1,
            "retrieval_mode": "vector",
            "metrics": {},
        }
    )

    # Retrieval should still return citations (no-op fallback).
    citations = out.get("citations") or []
    assert citations and citations[0].get("chunk_id") == "a"

    trace = out.get("retrieval_trace") or {}
    post = (trace.get("post_rerank") or {})
    assert post.get("enabled") is True
    assert post.get("used") is False
    assert post.get("skip_reason") == "error"
    assert post.get("error")
