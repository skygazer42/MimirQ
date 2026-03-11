from __future__ import annotations

import uuid

import pytest
from langchain_core.documents import Document


class _FakeRetriever:
    def __init__(self, *, docs: list[Document]) -> None:
        self._docs = list(docs)
        self._last_debug_metrics: dict = {}

    def model_copy(self, **_kwargs):  # noqa: ANN001, ANN002, ANN003
        return self

    def invoke(self, _q: str):  # noqa: ANN001
        return list(self._docs)


def _mk_doc(i: int, *, grade: str | None, score: float | None) -> Document:
    chunk_id = f"c{i}"
    cq: dict = {}
    if grade is not None:
        cq["grade"] = grade
    if score is not None:
        cq["score"] = score
    cq["labels"] = ["Header", "Noisy_Symbols", "Short", "ExtraLabel"] if grade is not None else []
    return Document(
        page_content=f"doc-{i}",
        id=chunk_id,
        metadata={
            "chunk_id": chunk_id,
            "document_id": str(uuid.uuid4()),
            "source": f"s-{i}.md",
            "score": max(0.0, 1.0 - (i * 0.01)),
            "chunk_quality": cq if cq else None,
        },
    )


def test_orchestrator_trace_includes_bounded_chunk_quality_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.retrieval.orchestrator as orch_mod
    from app.core.config import settings

    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_MULTI_QUERY", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_HYDE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_QUERY_DECOMPOSITION", False, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_QUERY_PARALLELISM", 1, raising=False)
    monkeypatch.setattr(settings, "KG_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "KG_CHAT_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_CHUNK_INJECTION_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_QUERY_EXPANSION_ENABLED", False, raising=False)

    import app.query.expand as expand_mod

    monkeypatch.setattr(expand_mod, "load_base_dictionary_rules", lambda: [], raising=True)
    monkeypatch.setattr(
        expand_mod,
        "generate_dictionary_expansions",
        lambda **_k: ([], {"enabled": False, "used": False}),
        raising=True,
    )

    docs = [
        _mk_doc(1, grade="good", score=0.95),
        _mk_doc(2, grade="ok", score=0.62),
        _mk_doc(3, grade="bad", score=0.21),
        _mk_doc(4, grade=None, score=None),
        _mk_doc(5, grade="good", score=0.88),
        _mk_doc(6, grade="bad", score=0.17),
        # Over-limit candidates should not inflate the summary.
        _mk_doc(7, grade="good", score=0.99),
        _mk_doc(8, grade="good", score=0.99),
    ]
    monkeypatch.setattr(orch_mod, "hybrid_retriever", _FakeRetriever(docs=docs), raising=True)

    out = orch_mod.run_retrieval(
        {
            "question": "q",
            "history": [],
            "tenant_id": str(uuid.uuid4()),
            "account_id": "u",
            "dataset_id": None,
            "document_ids": [str(uuid.uuid4())],
            "top_k": 6,
            "retrieval_mode": "vector",
            "metrics": {},
        }
    )

    trace = out.get("retrieval_trace") or {}
    citations = trace.get("citations") or {}
    cq = citations.get("chunk_quality") or {}

    assert cq.get("schema") == "mimirq.chunk_quality_trace.v1"
    assert int(cq.get("candidates_considered") or 0) == 6

    buckets = cq.get("bucket_counts") or {}
    assert buckets.get("good") == 2
    assert buckets.get("ok") == 1
    assert buckets.get("bad") == 2
    assert buckets.get("unknown") == 1

    top = cq.get("top_candidates") or []
    assert len(top) <= 8
    assert all("content" not in (row or {}) for row in top if isinstance(row, dict))
    assert all(len((row or {}).get("labels") or []) <= 3 for row in top if isinstance(row, dict))

