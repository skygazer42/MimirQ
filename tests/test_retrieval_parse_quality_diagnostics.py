from __future__ import annotations

import uuid

from langchain_core.documents import Document


class _FixedRetriever:
    def __init__(self, docs):  # noqa: ANN001
        self._docs = list(docs or [])
        self._last_debug_metrics: dict = {}

    def model_copy(self, **_kwargs):  # noqa: ANN001, ANN002, ANN003
        return self

    def invoke(self, _q: str):  # noqa: ANN001
        return list(self._docs)


def _base_state() -> dict:
    return {
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


def test_orchestrator_emits_parse_quality_alert_and_trace(monkeypatch) -> None:  # noqa: ANN001
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
    monkeypatch.setattr(settings, "RETRIEVAL_PARSE_QUALITY_LOW_THRESHOLD", 0.35, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_PARSE_QUALITY_ALERT_RATIO", 0.5, raising=False)

    import app.query.expand as expand_mod

    monkeypatch.setattr(expand_mod, "load_base_dictionary_rules", lambda: [], raising=True)
    monkeypatch.setattr(
        expand_mod,
        "generate_dictionary_expansions",
        lambda **_k: ([], {"enabled": False, "used": False}),
        raising=True,
    )

    docs = [
        Document(page_content="a", id=str(uuid.uuid4()), metadata={"document_id": str(uuid.uuid4()), "score": 0.9, "doc_parse_quality_score": 0.1}),
        Document(page_content="b", id=str(uuid.uuid4()), metadata={"document_id": str(uuid.uuid4()), "score": 0.8, "doc_parse_quality_score": 0.2}),
        Document(page_content="c", id=str(uuid.uuid4()), metadata={"document_id": str(uuid.uuid4()), "score": 0.7, "doc_parse_quality_score": 0.9}),
    ]
    monkeypatch.setattr(orch_mod, "hybrid_retriever", _FixedRetriever(docs), raising=True)

    out = orch_mod.run_retrieval(_base_state())
    metrics = out.get("metrics") or {}
    pq = metrics.get("parse_quality") or {}

    assert int(pq.get("considered") or 0) == 3
    assert int(pq.get("low_count") or 0) == 2
    assert float(pq.get("low_ratio") or 0.0) > 0.6
    assert bool(pq.get("alert")) is True
    assert str(metrics.get("parse_quality_recommendation") or "") in {
        "medium_parse_risk_prioritize_low_quality_docs",
        "high_parse_risk_reparse_documents",
    }

    trace = out.get("retrieval_trace") or {}
    trace_pq = trace.get("parse_quality") or {}
    assert bool(trace_pq.get("alert")) is True
    assert int(trace_pq.get("considered") or 0) == 3


def test_orchestrator_parse_quality_handles_missing_metadata(monkeypatch) -> None:  # noqa: ANN001
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

    docs = [Document(page_content="a", id=str(uuid.uuid4()), metadata={"document_id": str(uuid.uuid4()), "score": 0.9})]
    monkeypatch.setattr(orch_mod, "hybrid_retriever", _FixedRetriever(docs), raising=True)

    out = orch_mod.run_retrieval(_base_state())
    pq = (out.get("metrics") or {}).get("parse_quality") or {}
    assert int(pq.get("considered") or 0) == 0
    assert str(pq.get("recommendation") or "") == "no_parse_quality_metadata"
