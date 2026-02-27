from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import pytest
from langchain_core.documents import Document

from app.core.config import settings
from app.rag.reranker.base import BaseReranker
from app.rag.reranker.types import RerankCandidate, RerankResult


@dataclass
class _CountingReranker(BaseReranker):
    calls: list[int]

    def rerank(self, query: str, candidates: Sequence[RerankCandidate], **_kwargs: Any) -> RerankResult:  # noqa: ARG002
        self.calls.append(1)
        ids = [str(c.id) for c in candidates]
        ordered = list(reversed(ids))
        score_map = {cid: float(len(ordered) - i) for i, cid in enumerate(ordered)}
        return RerankResult(ordered_ids=ordered, score_map=score_map, provider="stub", model_used="stub")


class _FakeRetriever:
    def __init__(self, *, docs: list[Document]) -> None:
        self._docs = list(docs)
        self._last_debug_metrics: dict = {}

    def model_copy(self, **_kwargs):  # noqa: ANN001, ANN002, ANN003
        return self

    def invoke(self, _q: str):  # noqa: ANN001
        return list(self._docs)


def test_evidence_post_rerank_cache_hits_avoid_duplicate_rerank_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.retrieval.orchestrator as orch_mod

    # Deterministic: disable any LLM-dependent query transforms.
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

    # Enable post-rerank + cache.
    monkeypatch.setattr(settings, "EVIDENCE_POST_RERANK_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "EVIDENCE_POST_RERANK_PROVIDER", "stub", raising=False)
    monkeypatch.setattr(settings, "EVIDENCE_POST_RERANK_TOP_N", 10, raising=False)
    monkeypatch.setattr(settings, "EVIDENCE_POST_RERANK_CACHE_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "EVIDENCE_POST_RERANK_CACHE_MAX_ENTRIES", 128, raising=False)
    monkeypatch.setattr(settings, "EVIDENCE_POST_RERANK_CACHE_TTL_SEC", 60, raising=False)

    # Clear any global cache state from other tests (best-effort).
    try:
        from app.rag.rerank_result_cache import clear_evidence_post_rerank_cache_for_tests

        clear_evidence_post_rerank_cache_for_tests()
    except Exception:
        pass

    calls: list[int] = []
    reranker = _CountingReranker(calls=calls)
    monkeypatch.setattr(orch_mod, "get_reranker", lambda _p: reranker, raising=True)

    doc_id = "doc"
    d1 = Document(page_content="a", id="a", metadata={"document_id": doc_id, "chunk_id": "a", "score": 0.1})
    d2 = Document(page_content="b", id="b", metadata={"document_id": doc_id, "chunk_id": "b", "score": 0.1})
    monkeypatch.setattr(orch_mod, "hybrid_retriever", _FakeRetriever(docs=[d1, d2]), raising=True)

    payload = {
        "question": "should-not-leak",
        "history": [],
        "tenant_id": "t",
        "account_id": "u",
        "dataset_id": None,
        "document_ids": [doc_id],
        "top_k": 2,
        "retrieval_mode": "vector",
        "metrics": {},
    }

    out1 = orch_mod.run_retrieval(dict(payload))
    out2 = orch_mod.run_retrieval(dict(payload))

    assert len(calls) == 1

    citations1 = out1.get("citations") or []
    citations2 = out2.get("citations") or []
    assert [c.get("chunk_id") for c in citations1][:2] == ["b", "a"]
    assert [c.get("chunk_id") for c in citations2][:2] == ["b", "a"]

    trace2 = out2.get("retrieval_trace") or {}
    dumped = str(trace2)
    assert "should-not-leak" not in dumped

