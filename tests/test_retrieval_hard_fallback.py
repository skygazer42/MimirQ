from __future__ import annotations

import uuid

from langchain_core.documents import Document


class _FallbackAwareRetriever:
    def __init__(self, *, retrieval_mode: str = "hybrid") -> None:
        self.retrieval_mode = str(retrieval_mode or "hybrid")
        self._last_debug_metrics: dict = {}

    def model_copy(self, *, update=None, **_kwargs):  # noqa: ANN003
        update = dict(update or {})
        return _FallbackAwareRetriever(retrieval_mode=str(update.get("retrieval_mode") or self.retrieval_mode))

    def invoke(self, _q: str):  # noqa: ANN001
        if self.retrieval_mode == "keyword":
            did = uuid.uuid4()
            cid = uuid.uuid4()
            return [
                Document(
                    page_content="fallback hit",
                    id=str(cid),
                    metadata={
                        "document_id": str(did),
                        "chunk_id": str(cid),
                        "chunk_index": 0,
                        "source": "fallback.md",
                        "score": 0.95,
                        "start_char": 0,
                        "end_char": 12,
                    },
                )
            ]
        return []


class _AlwaysEmptyRetriever:
    def __init__(self, *, retrieval_mode: str = "hybrid") -> None:
        self.retrieval_mode = str(retrieval_mode or "hybrid")
        self._last_debug_metrics: dict = {}

    def model_copy(self, *, update=None, **_kwargs):  # noqa: ANN003
        update = dict(update or {})
        return _AlwaysEmptyRetriever(retrieval_mode=str(update.get("retrieval_mode") or self.retrieval_mode))

    def invoke(self, _q: str):  # noqa: ANN001
        return []


def test_orchestrator_hard_fallback_adds_citations_when_primary_empty(monkeypatch) -> None:  # noqa: ANN001
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
    monkeypatch.setattr(settings, "RETRIEVAL_HARD_FALLBACK_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_HARD_FALLBACK_TOP_K", 30, raising=False)

    import app.query.expand as expand_mod

    monkeypatch.setattr(expand_mod, "load_base_dictionary_rules", lambda: [], raising=True)
    monkeypatch.setattr(
        expand_mod,
        "generate_dictionary_expansions",
        lambda **_k: ([], {"enabled": False, "used": False}),
        raising=True,
    )

    monkeypatch.setattr(orch_mod, "hybrid_retriever", _FallbackAwareRetriever(), raising=True)

    out = orch_mod.run_retrieval(
        {
            "question": "q",
            "history": [],
            "tenant_id": str(uuid.uuid4()),
            "account_id": "u",
            "dataset_id": None,
            "document_ids": [str(uuid.uuid4())],
            "top_k": 5,
            "retrieval_mode": "hybrid",
            "metrics": {},
        }
    )

    citations = out.get("citations") or []
    assert citations, "hard fallback should recover citations"

    metrics = out.get("metrics") or {}
    assert metrics.get("hard_fallback_enabled") is True
    assert metrics.get("hard_fallback_attempted") is True
    assert metrics.get("hard_fallback_used") is True
    assert int(metrics.get("hard_fallback_added_docs") or 0) > 0

    trace = out.get("retrieval_trace") or {}
    fallback = trace.get("hard_fallback") or {}
    assert fallback.get("enabled") is True
    assert fallback.get("attempted") is True
    assert fallback.get("used") is True


def test_orchestrator_hard_fallback_reports_empty_reason_when_still_empty(monkeypatch) -> None:  # noqa: ANN001
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
    monkeypatch.setattr(settings, "RETRIEVAL_HARD_FALLBACK_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_HARD_FALLBACK_TOP_K", 20, raising=False)

    import app.query.expand as expand_mod

    monkeypatch.setattr(expand_mod, "load_base_dictionary_rules", lambda: [], raising=True)
    monkeypatch.setattr(
        expand_mod,
        "generate_dictionary_expansions",
        lambda **_k: ([], {"enabled": False, "used": False}),
        raising=True,
    )

    monkeypatch.setattr(orch_mod, "hybrid_retriever", _AlwaysEmptyRetriever(), raising=True)

    out = orch_mod.run_retrieval(
        {
            "question": "q",
            "history": [],
            "tenant_id": str(uuid.uuid4()),
            "account_id": "u",
            "dataset_id": None,
            "document_ids": [str(uuid.uuid4())],
            "top_k": 5,
            "retrieval_mode": "hybrid",
            "metrics": {},
        }
    )

    assert out.get("citations") == []
    metrics = out.get("metrics") or {}
    empty = metrics.get("empty_retrieval") or {}
    assert "hard_fallback_no_hit" in (empty.get("reasons") or [])
    assert (empty.get("signals") or {}).get("hard_fallback_attempted") == 1


def test_orchestrator_contract_mode_enables_deterministic_fallback(monkeypatch) -> None:  # noqa: ANN001
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
    monkeypatch.setattr(settings, "RETRIEVAL_HARD_FALLBACK_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_CONTRACT_MODE", "deterministic_recall", raising=False)

    import app.query.expand as expand_mod

    monkeypatch.setattr(expand_mod, "load_base_dictionary_rules", lambda: [], raising=True)
    monkeypatch.setattr(
        expand_mod,
        "generate_dictionary_expansions",
        lambda **_k: ([], {"enabled": False, "used": False}),
        raising=True,
    )

    monkeypatch.setattr(orch_mod, "hybrid_retriever", _FallbackAwareRetriever(), raising=True)

    out = orch_mod.run_retrieval(
        {
            "question": "q",
            "history": [],
            "tenant_id": str(uuid.uuid4()),
            "account_id": "u",
            "dataset_id": None,
            "document_ids": [str(uuid.uuid4())],
            "top_k": 5,
            "retrieval_mode": "hybrid",
            "metrics": {},
        }
    )

    citations = out.get("citations") or []
    assert citations
    metrics = out.get("metrics") or {}
    assert metrics.get("retrieval_contract_mode") == "deterministic_recall"
    assert metrics.get("retrieval_contract_deterministic_recall") is True
    assert metrics.get("hard_fallback_attempted") is True
