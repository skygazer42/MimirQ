from __future__ import annotations

from uuid import uuid4

import pytest
from langchain_core.callbacks import CallbackManagerForRetrieverRun

from app.core.config import settings
from app.rag.retriever import HybridRetriever


class _StubVectorStore:
    def __init__(self, *, results):  # noqa: ANN001
        self._results = list(results)

    def search(self, **_kwargs):  # noqa: ANN003
        return list(self._results)


def test_retriever_debug_metrics_include_channel_timing_and_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    retriever = HybridRetriever()
    retriever.tenant_id = uuid4()
    retriever.dataset_id = uuid4()

    # Ensure the lexical DB channel never touches Postgres in this unit test.
    monkeypatch.setattr(settings, "LEXICAL_DB_ENABLED", False, raising=False)

    # Stub vector store retrieval.
    vector_candidates = [
        {
            "chunk_id": str(uuid4()),
            "content": "vector hit",
            "metadata": {"document_id": str(uuid4()), "chunk_index": 0},
            "score": 0.9,
        }
    ]
    stub_store = _StubVectorStore(results=vector_candidates)
    monkeypatch.setattr("app.storage.vector.factory.get_vector_store", lambda: stub_store, raising=True)
    # `HybridRetriever` may import `get_vector_store` directly; patch both for robustness.
    monkeypatch.setattr("app.rag.retriever.get_vector_store", lambda: stub_store, raising=False)

    # Stub BM25 retrieval.
    bm25_candidates = [
        {
            "chunk_id": str(uuid4()),
            "content": "bm25 hit",
            "metadata": {"document_id": str(uuid4()), "chunk_index": 0},
            "score": 0.8,
        }
    ]
    monkeypatch.setattr(
        HybridRetriever,
        "_search_bm25",
        lambda _self, **_kwargs: list(bm25_candidates),
        raising=True,
    )

    # Avoid DB access in enrichment / expansion paths; this test only validates metrics shape.
    monkeypatch.setattr(HybridRetriever, "_enrich_results_with_db_metadata", lambda _self, r, **_k: r, raising=True)
    monkeypatch.setattr(HybridRetriever, "_expand_results_with_neighbors", lambda _self, r: r, raising=True)
    monkeypatch.setattr(HybridRetriever, "_auto_merge_parent_child", lambda _self, r: r, raising=True)

    retriever._get_relevant_documents(
        "hi",
        run_manager=CallbackManagerForRetrieverRun.get_noop_manager(),
    )

    debug = retriever._last_debug_metrics
    assert isinstance(debug, dict)

    timing = debug.get("timing")
    counts = debug.get("counts")
    assert isinstance(timing, dict)
    assert isinstance(counts, dict)

    for key in ("vector_ms", "bm25_ms", "lexical_ms", "fusion_ms"):
        assert key in timing

    for key in ("vector_candidates", "bm25_candidates"):
        assert key in counts
