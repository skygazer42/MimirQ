from __future__ import annotations

from uuid import uuid4

import pytest
from langchain_core.callbacks import CallbackManagerForRetrieverRun

from app.core.config import settings
from app.rag.retriever import HybridRetriever


def test_resolve_rerank_profile_returns_sweet_spot_search_k() -> None:
    from app.config.rerank_profile import get_rerank_profile

    profile = get_rerank_profile("sweet_spot")

    assert profile.name == "sweet_spot"
    assert profile.search_k == 20


class _StubVectorStore:
    def __init__(self, *, results):  # noqa: ANN001
        self._results = list(results)

    def search(self, **_kwargs):  # noqa: ANN003
        return list(self._results)


def test_hybrid_retriever_applies_rerank_profile_search_k_floor(monkeypatch: pytest.MonkeyPatch) -> None:
    retriever = HybridRetriever()
    retriever.tenant_id = uuid4()
    retriever.dataset_id = uuid4()
    retriever.k = 5
    retriever.enable_reranker = True

    monkeypatch.setattr(settings, "RERANK_PROFILE", "sweet_spot", raising=False)
    monkeypatch.setattr(settings, "LEXICAL_DB_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "SPARSE_RETRIEVAL_ENABLED", False, raising=False)

    candidates = [
        {
            "chunk_id": str(uuid4()),
            "content": "vector hit",
            "metadata": {"document_id": str(uuid4()), "chunk_index": 0},
            "score": 0.9,
        }
        for _ in range(8)
    ]

    stub_store = _StubVectorStore(results=candidates)
    monkeypatch.setattr("app.storage.vector.factory.get_vector_store", lambda: stub_store, raising=True)
    monkeypatch.setattr("app.rag.retriever.get_vector_store", lambda: stub_store, raising=False)
    monkeypatch.setattr(HybridRetriever, "_search_bm25", lambda _self, **_kwargs: [], raising=True)
    monkeypatch.setattr(HybridRetriever, "_enrich_results_with_db_metadata", lambda _self, r, **_k: r, raising=True)
    monkeypatch.setattr(HybridRetriever, "_expand_results_with_neighbors", lambda _self, r: r, raising=True)
    monkeypatch.setattr(HybridRetriever, "_auto_merge_parent_child", lambda _self, r: r, raising=True)

    retriever._get_relevant_documents("hi", run_manager=CallbackManagerForRetrieverRun.get_noop_manager())

    debug = retriever._last_debug_metrics
    assert debug["search_k"] == 20
    assert debug["requested_k"] == 5
    assert debug["rerank_profile"] == "sweet_spot"
