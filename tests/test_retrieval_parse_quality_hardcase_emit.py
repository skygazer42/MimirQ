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


def _patch_common(monkeypatch) -> None:  # noqa: ANN001
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
    monkeypatch.setattr(settings, "RAG_ABSTAIN_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_HARDCASE_EMIT_ENABLED", False, raising=False)

    monkeypatch.setattr(settings, "RETRIEVAL_PARSE_QUALITY_LOW_THRESHOLD", 0.35, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_PARSE_QUALITY_ALERT_RATIO", 0.5, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_PARSE_RISK_HARDCASE_MIN_LOW_RATIO", 0.5, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_PARSE_RISK_HARDCASE_MIN_CONSIDERED", 2, raising=False)

    import app.query.expand as expand_mod

    monkeypatch.setattr(expand_mod, "load_base_dictionary_rules", lambda: [], raising=True)
    monkeypatch.setattr(
        expand_mod,
        "generate_dictionary_expansions",
        lambda **_k: ([], {"enabled": False, "used": False}),
        raising=True,
    )


def test_orchestrator_emits_parse_risk_hardcase_candidate_when_enabled(monkeypatch) -> None:  # noqa: ANN001
    import app.rag.retrieval.orchestrator as orch_mod
    from app.core.config import settings

    _patch_common(monkeypatch)
    monkeypatch.setattr(settings, "RETRIEVAL_PARSE_RISK_HARDCASE_EMIT_ENABLED", True, raising=False)

    docs = [
        Document(page_content="a", id=str(uuid.uuid4()), metadata={"document_id": str(uuid.uuid4()), "doc_parse_quality_score": 0.1}),
        Document(page_content="b", id=str(uuid.uuid4()), metadata={"document_id": str(uuid.uuid4()), "doc_parse_quality_score": 0.2}),
    ]
    monkeypatch.setattr(orch_mod, "hybrid_retriever", _FixedRetriever(docs), raising=True)
    monkeypatch.setattr(
        orch_mod,
        "build_citations_from_docs",
        lambda *_a, **_k: [
            {
                "chunk_id": "c1",
                "document_id": "d1",
                "snippet": "ok",
                "evidence_start_char": 0,
                "evidence_end_char": 2,
                "relevance_score": 0.9,
            }
        ],
        raising=True,
    )

    out = orch_mod.run_retrieval(_base_state())
    metrics = out.get("metrics") or {}
    hc = metrics.get("hardcase_candidate") or {}

    assert hc.get("schema") == "mimirq.hardcase_candidate.v1"
    assert hc.get("reason") == "parse_risk_tail"
    assert hc.get("parse_risk_level") in {"high", "medium"}
    assert isinstance(hc.get("dedupe_key"), str) and len(str(hc.get("dedupe_key") or "")) >= 16


def test_orchestrator_skips_parse_risk_hardcase_candidate_when_disabled(monkeypatch) -> None:  # noqa: ANN001
    import app.rag.retrieval.orchestrator as orch_mod
    from app.core.config import settings

    _patch_common(monkeypatch)
    monkeypatch.setattr(settings, "RETRIEVAL_PARSE_RISK_HARDCASE_EMIT_ENABLED", False, raising=False)

    docs = [
        Document(page_content="a", id=str(uuid.uuid4()), metadata={"document_id": str(uuid.uuid4()), "doc_parse_quality_score": 0.1}),
        Document(page_content="b", id=str(uuid.uuid4()), metadata={"document_id": str(uuid.uuid4()), "doc_parse_quality_score": 0.2}),
    ]
    monkeypatch.setattr(orch_mod, "hybrid_retriever", _FixedRetriever(docs), raising=True)
    monkeypatch.setattr(
        orch_mod,
        "build_citations_from_docs",
        lambda *_a, **_k: [
            {
                "chunk_id": "c1",
                "document_id": "d1",
                "snippet": "ok",
                "evidence_start_char": 0,
                "evidence_end_char": 2,
                "relevance_score": 0.9,
            }
        ],
        raising=True,
    )

    out = orch_mod.run_retrieval(_base_state())
    metrics = out.get("metrics") or {}
    assert metrics.get("hardcase_candidate") is None
