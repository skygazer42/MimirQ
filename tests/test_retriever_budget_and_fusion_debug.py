from __future__ import annotations

import json
from uuid import uuid4

import pytest
from langchain_core.callbacks import CallbackManagerForRetrieverRun

from app.core.config import settings
from app.rag.retriever import HybridRetriever


def test_sanitize_retriever_debug_includes_budget_fields_and_strips_text() -> None:
    from app.rag.retrieval.orchestrator import _sanitize_retriever_debug

    dbg = {
        "requested_k": 5,
        "search_k": 10,
        "fetch_k": 20,
        "overfetch_enabled": True,
        "overfetch_multiplier": 3,
        "overfetch_cap_k": 100,
        "milvus_doc_id_pushdown_skipped": True,
        "milvus_expr_max_doc_ids": 500,
        "query_normalization": {
            "original": "user secret query",
            "normalized": "user secret query",
            "applied_rules": ["strip"],
        },
        "channels": {
            "budget": {
                "fetch_k": 20,
                "mmr_fetch_k_multiplier": 4,
            }
        },
    }

    out = _sanitize_retriever_debug(dbg)
    assert isinstance(out, dict)

    # Budget fields should be surfaced for diagnosis.
    assert out.get("fetch_k") == 20
    assert out.get("overfetch_multiplier") == 3
    assert out.get("overfetch_cap_k") == 100
    assert out.get("milvus_doc_id_pushdown_skipped") is True
    assert out.get("milvus_expr_max_doc_ids") == 500

    # PII-safe: no raw query text.
    dumped = json.dumps(out, ensure_ascii=False)
    assert "user secret query" not in dumped


class _StubVectorStore:
    def __init__(self, *, results):  # noqa: ANN001
        self._results = list(results)

    def search(self, **_kwargs):  # noqa: ANN003
        return list(self._results)


def test_hybrid_retriever_records_budgeted_rrf_prefix_selection_meta(monkeypatch: pytest.MonkeyPatch) -> None:
    retriever = HybridRetriever()
    retriever.tenant_id = uuid4()
    retriever.dataset_id = uuid4()
    retriever.k = 6
    retriever.fusion_strategy = "budgeted_rrf"

    # Keep this unit-level (no Postgres).
    monkeypatch.setattr(settings, "LEXICAL_DB_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "SPARSE_RETRIEVAL_ENABLED", False, raising=False)

    vector_candidates = []
    bm25_candidates = []
    for _ in range(8):
        vector_candidates.append(
            {
                "chunk_id": str(uuid4()),
                "content": "vector hit",
                "metadata": {"document_id": str(uuid4()), "chunk_index": 0},
                "score": 0.9,
            }
        )
    for _ in range(8):
        bm25_candidates.append(
            {
                "chunk_id": str(uuid4()),
                "content": "bm25 hit",
                "metadata": {"document_id": str(uuid4()), "chunk_index": 0},
                "score": 0.8,
            }
        )

    stub_store = _StubVectorStore(results=vector_candidates)
    monkeypatch.setattr("app.storage.vector.factory.get_vector_store", lambda: stub_store, raising=True)
    monkeypatch.setattr("app.rag.retriever.get_vector_store", lambda: stub_store, raising=False)

    monkeypatch.setattr(
        HybridRetriever,
        "_search_bm25",
        lambda _self, **_kwargs: list(bm25_candidates),
        raising=True,
    )

    monkeypatch.setattr(HybridRetriever, "_enrich_results_with_db_metadata", lambda _self, r, **_k: r, raising=True)
    monkeypatch.setattr(HybridRetriever, "_expand_results_with_neighbors", lambda _self, r: r, raising=True)
    monkeypatch.setattr(HybridRetriever, "_auto_merge_parent_child", lambda _self, r: r, raising=True)

    retriever._get_relevant_documents(
        "hi",
        run_manager=CallbackManagerForRetrieverRun.get_noop_manager(),
    )

    debug = retriever._last_debug_metrics
    channels = debug.get("channels") or {}
    assert isinstance(channels, dict)
    meta = channels.get("fusion_budgeted_rrf")
    assert isinstance(meta, dict)
    assert meta.get("k_prefix") == 6
    budgets = meta.get("budgets") or {}
    assert isinstance(budgets, dict)
    assert set(budgets.keys()) >= {"vector", "bm25", "lexical", "sparse"}

