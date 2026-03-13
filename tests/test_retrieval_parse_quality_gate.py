from __future__ import annotations

import uuid

import pytest
from langchain_core.documents import Document


class _StaticRetriever:
    def __init__(self, docs: list[Document]) -> None:
        self._docs = list(docs or [])
        self._last_debug_metrics: dict = {}

    def model_copy(self, **_kwargs):  # noqa: ANN001, ANN002, ANN003
        return self

    def invoke(self, _q: str):  # noqa: ANN001
        return list(self._docs)


def _mk_doc(score: float) -> Document:
    chunk_id = uuid.uuid4()
    document_id = uuid.uuid4()
    return Document(
        page_content=f"doc-{score}",
        id=str(chunk_id),
        metadata={
            "chunk_id": str(chunk_id),
            "document_id": str(document_id),
            "source": "x.md",
            "score": 0.9,
            "retrieval_score": 0.9,
            "doc_parse_quality_score": float(score),
        },
    )


def test_parse_quality_gate_strict_blocks_with_abstain(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.retrieval.orchestrator as orch_mod
    from app.core.config import settings

    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_MULTI_QUERY", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_HYDE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_QUERY_DECOMPOSITION", False, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_QUERY_PARALLELISM", 1, raising=False)
    monkeypatch.setattr(settings, "RAG_ABSTAIN_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_ABSTAIN_MIN_CITATIONS", 0, raising=False)
    monkeypatch.setattr(settings, "RAG_ABSTAIN_MIN_TOP_RELEVANCE_SCORE", 0.0, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_PARSE_QUALITY_GATE_PROFILE", "strict", raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_PARSE_QUALITY_LOW_THRESHOLD", 0.35, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_PARSE_QUALITY_ALERT_RATIO", 0.5, raising=False)

    monkeypatch.setattr(
        orch_mod,
        "hybrid_retriever",
        _StaticRetriever([_mk_doc(0.1), _mk_doc(0.2), _mk_doc(0.3)]),
        raising=True,
    )

    out = orch_mod.run_retrieval(
        {
            "question": "q",
            "history": [],
            "tenant_id": str(uuid.uuid4()),
            "account_id": "u",
            "dataset_id": None,
            "document_ids": [str(uuid.uuid4())],
            "top_k": 5,
            "retrieval_mode": "vector",
            "metrics": {},
        }
    )
    metrics = out.get("metrics") or {}
    assert bool(metrics.get("parse_quality_gate_violation")) is True
    assert bool(metrics.get("parse_quality_gate_blocked")) is True
    assert bool(metrics.get("abstain_triggered")) is True
    assert str(metrics.get("abstain_reason") or "") == "parse_quality_gate_strict"


def test_parse_quality_gate_warn_does_not_force_abstain(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.retrieval.orchestrator as orch_mod
    from app.core.config import settings

    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_MULTI_QUERY", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_HYDE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_QUERY_DECOMPOSITION", False, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_QUERY_PARALLELISM", 1, raising=False)
    monkeypatch.setattr(settings, "RAG_ABSTAIN_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_ABSTAIN_MIN_CITATIONS", 0, raising=False)
    monkeypatch.setattr(settings, "RAG_ABSTAIN_MIN_TOP_RELEVANCE_SCORE", 0.0, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_PARSE_QUALITY_GATE_PROFILE", "warn", raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_PARSE_QUALITY_LOW_THRESHOLD", 0.35, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_PARSE_QUALITY_ALERT_RATIO", 0.5, raising=False)

    monkeypatch.setattr(
        orch_mod,
        "hybrid_retriever",
        _StaticRetriever([_mk_doc(0.1), _mk_doc(0.2), _mk_doc(0.3)]),
        raising=True,
    )

    out = orch_mod.run_retrieval(
        {
            "question": "q",
            "history": [],
            "tenant_id": str(uuid.uuid4()),
            "account_id": "u",
            "dataset_id": None,
            "document_ids": [str(uuid.uuid4())],
            "top_k": 5,
            "retrieval_mode": "vector",
            "metrics": {},
        }
    )
    metrics = out.get("metrics") or {}
    assert bool(metrics.get("parse_quality_gate_violation")) is True
    assert bool(metrics.get("parse_quality_gate_blocked")) is False
    assert bool(metrics.get("abstain_triggered")) is False
