from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import pytest
from langchain_core.documents import Document

from app.infrastructure.config import settings
from app.rag.retrieval.reranking.base import BaseReranker
from app.rag.retrieval.reranking.types import RerankCandidate, RerankResult


@dataclass
class _StubReranker(BaseReranker):
    ordered_ids: list[str]
    score_map: dict[str, float]
    provider_id: str = "stub_rerank"

    def rerank(self, query: str, candidates: Sequence[RerankCandidate], **_kwargs: Any) -> RerankResult:  # noqa: ARG002
        ids = {str(c.id) for c in candidates}
        ordered = [cid for cid in self.ordered_ids if cid in ids]
        scores = {cid: float(self.score_map[cid]) for cid in ordered if cid in self.score_map}
        return RerankResult(
            ordered_ids=ordered,
            score_map=scores,
            provider=self.provider_id,
            model_used="stub-model",
            elapsed_sec=0.0,
        )


class _FakeRetriever:
    def __init__(self, *, docs: list[Document]) -> None:
        self._docs = list(docs)
        self._last_debug_metrics: dict = {}

    def model_copy(self, **_kwargs):  # noqa: ANN001, ANN002, ANN003
        return self

    def invoke(self, _q: str):  # noqa: ANN001
        return list(self._docs)


def test_post_rerank_score_calibration_can_reorder_using_retrieval_signal(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.retrieval.orchestrator as orch_mod
    from app.rag.retrieval.stages import followup as followup_stage
    from app.rag.retrieval.stages import post_rerank as post_rerank_stage
    from app.rag.retrieval.stages import preparation as preparation_stage
    from app.rag.retrieval.stages import requirements as requirements_stage

    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_MULTI_QUERY", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_HYDE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_QUERY_DECOMPOSITION", False, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_QUERY_PARALLELISM", 1, raising=False)
    monkeypatch.setattr(settings, "RAG_VISIBLE_EVIDENCE_ONLY_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_ABSTAIN_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "KG_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "KG_CHAT_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_CHUNK_INJECTION_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_QUERY_EXPANSION_ENABLED", False, raising=False)

    monkeypatch.setattr(settings, "EVIDENCE_POST_RERANK_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "EVIDENCE_POST_RERANK_PROVIDER", "stub", raising=False)
    monkeypatch.setattr(settings, "EVIDENCE_POST_RERANK_TOP_N", 2, raising=False)
    monkeypatch.setattr(settings, "EVIDENCE_POST_RERANK_PIPELINE_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "EVIDENCE_POST_RERANK_CACHE_ENABLED", False)
    monkeypatch.setattr(settings, "EVIDENCE_POST_RERANK_SCORE_CALIBRATION_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "EVIDENCE_POST_RERANK_SCORE_CALIBRATION_ALPHA", 0.2, raising=False)

    doc_id = "00000000-0000-0000-0000-000000000001"
    d1 = Document(page_content="a", id="a", metadata={"document_id": doc_id, "chunk_id": "a", "score": 0.95})
    d2 = Document(page_content="b", id="b", metadata={"document_id": doc_id, "chunk_id": "b", "score": 0.20})
    retriever_port = _FakeRetriever(docs=[d1, d2])
    monkeypatch.setattr(preparation_stage, "hybrid_retriever", retriever_port, raising=True)
    monkeypatch.setattr(followup_stage, "hybrid_retriever", retriever_port, raising=True)
    monkeypatch.setattr(requirements_stage, "hybrid_retriever", retriever_port, raising=True)

    def _fake_get_reranker(_provider: str, **_kwargs: Any) -> BaseReranker:
        return _StubReranker(
            ordered_ids=["b", "a"],
            score_map={"b": 0.99, "a": 0.98},
        )

    monkeypatch.setattr(post_rerank_stage, "get_reranker_for_retrieval", _fake_get_reranker, raising=True)

    out = orch_mod.run_retrieval(
        {
            "question": "q",
            "history": [],
            "tenant_id": "t",
            "account_id": "u",
            "dataset_id": None,
            "document_ids": [doc_id],
            "top_k": 2,
            "retrieval_mode": "vector",
            "metrics": {},
        }
    )

    citations = out.get("citations") or []
    assert [c.get("chunk_id") for c in citations] == ["a", "b"]
    assert float(citations[0].get("rerank_score_calibrated") or 0.0) > float(
        citations[1].get("rerank_score_calibrated") or 0.0
    )

    metrics = out.get("metrics") or {}
    assert metrics.get("evidence_post_rerank_score_calibration_enabled") is True
    assert metrics.get("evidence_post_rerank_score_calibration_used") is True
    calibration = metrics.get("evidence_post_rerank_score_calibration") or {}
    assert int(calibration.get("moved_positions") or 0) >= 1
