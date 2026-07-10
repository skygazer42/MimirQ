
import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import pytest
from langchain_core.documents import Document

from app.core.config import settings
from app.rag.reranker.base import BaseReranker
from app.rag.reranker.types import RerankCandidate, RerankResult


@dataclass
class _StubReranker(BaseReranker):
    provider_id: str
    ordered: list[str]
    expected_candidates: list[str] | None = None

    def rerank(self, query: str, candidates: Sequence[RerankCandidate], **_kwargs: Any) -> RerankResult:  # noqa: ARG002
        ids = [str(c.id) for c in candidates]
        if self.expected_candidates is not None:
            assert ids == self.expected_candidates
        score_map = {cid: float(len(self.ordered) - i) for i, cid in enumerate(self.ordered)}
        return RerankResult(ordered_ids=list(self.ordered), score_map=score_map, provider=self.provider_id, model_used="stub")


class _FakeRetriever:
    def __init__(self, *, docs: list[Document]) -> None:
        self._docs = list(docs)
        self._last_debug_metrics: dict = {}

    def model_copy(self, **_kwargs):  # noqa: ANN001, ANN002, ANN003
        return self

    def invoke(self, _q: str):  # noqa: ANN001
        return list(self._docs)


def test_orchestrator_evidence_post_rerank_pipeline_applies_stages(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.retrieval.orchestrator as orch_mod

    # Deterministic: no extra LLM features.
    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_MULTI_QUERY", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_HYDE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_QUERY_DECOMPOSITION", False, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_QUERY_PARALLELISM", 1, raising=False)
    monkeypatch.setattr(settings, "RAG_VISIBLE_EVIDENCE_ONLY_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_ABSTAIN_ENABLED", False, raising=False)

    # Disable KG work.
    monkeypatch.setattr(settings, "KG_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "KG_CHAT_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_CHUNK_INJECTION_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_QUERY_EXPANSION_ENABLED", False, raising=False)

    # Enable post-rerank + pipeline.
    monkeypatch.setattr(settings, "EVIDENCE_POST_RERANK_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "EVIDENCE_POST_RERANK_PROVIDER", "ltr", raising=False)
    monkeypatch.setattr(settings, "EVIDENCE_POST_RERANK_TOP_N", 10, raising=False)
    monkeypatch.setattr(settings, "EVIDENCE_POST_RERANK_PIPELINE_ENABLED", True, raising=False)

    pipeline = [
        {"provider": "stage1", "top_n": 3},
        {"provider": "stage2", "top_n": 2},
    ]
    monkeypatch.setattr(settings, "EVIDENCE_POST_RERANK_PIPELINE", json.dumps(pipeline), raising=False)

    # Retriever returns a->b->c initially.
    doc_id = "doc"
    d1 = Document(page_content="a", id="a", metadata={"document_id": doc_id, "chunk_id": "a", "score": 0.1})
    d2 = Document(page_content="b", id="b", metadata={"document_id": doc_id, "chunk_id": "b", "score": 0.1})
    d3 = Document(page_content="c", id="c", metadata={"document_id": doc_id, "chunk_id": "c", "score": 0.1})
    monkeypatch.setattr(orch_mod, "hybrid_retriever", _FakeRetriever(docs=[d1, d2, d3]), raising=True)

    # Stage1 reorders (b, a, c). Stage2 runs only on top-2 and swaps back to (a, b).
    def _fake_get_reranker(provider: str, **_kwargs: Any) -> BaseReranker:  # noqa: ANN001
        if provider == "stage1":
            return _StubReranker(provider_id="stage1", ordered=["b", "a", "c"], expected_candidates=["a", "b", "c"])
        if provider == "stage2":
            return _StubReranker(provider_id="stage2", ordered=["a", "b"], expected_candidates=["b", "a"])
        raise AssertionError(f"unexpected provider: {provider}")

    monkeypatch.setattr(orch_mod, "get_reranker", _fake_get_reranker, raising=True)

    out = orch_mod.run_retrieval(
        {
            "question": "q",
            "history": [],
            "tenant_id": "t",
            "account_id": "u",
            "dataset_id": None,
            "document_ids": [doc_id],
            "top_k": 3,
            "retrieval_mode": "vector",
            "metrics": {},
        }
    )

    citations = out.get("citations") or []
    assert [c.get("chunk_id") for c in citations] == ["a", "b", "c"]
    assert citations[0].get("reranker_provider") in {"stage2", "pipeline"}

