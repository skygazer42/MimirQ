
import uuid


class _EmptyRetriever:
    def __init__(self) -> None:
        self._last_debug_metrics: dict = {}

    def model_copy(self, **_kwargs):  # noqa: ANN001, ANN002, ANN003
        return self

    def invoke(self, _q: str):  # noqa: ANN001
        return []


def test_orchestrator_strict_span_mode_filters_spanless_citations(monkeypatch) -> None:  # noqa: ANN001
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
    monkeypatch.setattr(settings, "RAG_EVIDENCE_REQUIRE_SPANS_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RAG_ABSTAIN_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_ABSTAIN_MIN_CITATIONS", 1, raising=False)

    import app.query.expand as expand_mod

    monkeypatch.setattr(expand_mod, "load_base_dictionary_rules", lambda: [], raising=True)
    monkeypatch.setattr(
        expand_mod,
        "generate_dictionary_expansions",
        lambda **_k: ([], {"enabled": False, "used": False}),
        raising=True,
    )

    monkeypatch.setattr(orch_mod, "hybrid_retriever", _EmptyRetriever(), raising=True)
    monkeypatch.setattr(
        orch_mod,
        "build_citations_from_docs",
        lambda *_a, **_k: [
            {
                "chunk_id": "c-no-span",
                "document_id": "d",
                "snippet": "no span",
                "evidence_start_char": None,
                "evidence_end_char": None,
                "relevance_score": 0.9,
            }
        ],
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
            "retrieval_mode": "hybrid",
            "metrics": {},
        }
    )

    assert out.get("citations") == []

    metrics = out.get("metrics") or {}
    assert metrics.get("evidence_span_strict_enabled") is True
    assert int(metrics.get("evidence_span_missing_citations") or 0) == 1
    assert metrics.get("abstain_triggered") is True


def test_orchestrator_contract_mode_evidence_strict_forces_span_gate(monkeypatch) -> None:  # noqa: ANN001
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
    monkeypatch.setattr(settings, "RAG_EVIDENCE_REQUIRE_SPANS_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_VISIBLE_EVIDENCE_ONLY_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_ABSTAIN_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_ABSTAIN_MIN_CITATIONS", 1, raising=False)

    import app.query.expand as expand_mod

    monkeypatch.setattr(expand_mod, "load_base_dictionary_rules", lambda: [], raising=True)
    monkeypatch.setattr(
        expand_mod,
        "generate_dictionary_expansions",
        lambda **_k: ([], {"enabled": False, "used": False}),
        raising=True,
    )

    monkeypatch.setattr(orch_mod, "hybrid_retriever", _EmptyRetriever(), raising=True)
    monkeypatch.setattr(
        orch_mod,
        "build_citations_from_docs",
        lambda *_a, **_k: [
            {
                "chunk_id": "c-no-span",
                "document_id": "d",
                "snippet": "no span",
                "evidence_start_char": None,
                "evidence_end_char": None,
                "relevance_score": 0.9,
            }
        ],
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
            "retrieval_mode": "hybrid",
            "retrieval_contract_mode": "evidence_strict",
            "metrics": {},
        }
    )

    assert out.get("citations") == []

    metrics = out.get("metrics") or {}
    assert metrics.get("retrieval_contract_mode") == "evidence_strict"
    assert metrics.get("evidence_span_strict_enabled") is True
    assert metrics.get("visible_evidence_only_enabled") is True
    assert int(metrics.get("evidence_span_missing_citations") or 0) == 1
