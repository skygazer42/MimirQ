
import uuid

from langchain_core.documents import Document


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


class _FallbackRetriever:
    def __init__(self, *, fallback: bool = False) -> None:
        self._fallback = bool(fallback)
        self._last_debug_metrics = {
            "channels": {
                "retrieval_degraded": False,
                "degraded_reasons": [],
                "attempted_channels": ["vector"],
                "successful_channels": ["vector"],
                "all_retrieval_channels_failed": False,
            }
        }

    def model_copy(self, **_kwargs):  # noqa: ANN001, ANN002, ANN003
        update = _kwargs.get("update") if isinstance(_kwargs, dict) else None
        fallback = isinstance(update, dict) and str(update.get("retrieval_mode") or "").strip().lower() == "keyword"
        return _FallbackRetriever(fallback=bool(fallback))

    def invoke(self, _q: str):  # noqa: ANN001
        chunk_id = "c-fallback" if self._fallback else "c-main"
        return [Document(page_content="doc", metadata={"document_id": "d", "chunk_id": chunk_id})]


def test_orchestrator_strict_span_empty_runs_single_deterministic_fallback(monkeypatch) -> None:  # noqa: ANN001
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

    monkeypatch.setattr(orch_mod, "hybrid_retriever", _FallbackRetriever(), raising=True)

    def _build_citations(docs, **_kwargs):  # noqa: ANN001, ANN202
        roles = {
            str((getattr(doc, "metadata", None) or {}).get("retrieval_role") or "")
            for doc in (docs or [])
        }
        if "hard_fallback" in roles:
            return [
                {
                    "chunk_id": "c-span",
                    "document_id": "d",
                    "snippet": "with span",
                    "evidence_start_char": 1,
                    "evidence_end_char": 4,
                    "relevance_score": 0.91,
                }
            ]
        return [
            {
                "chunk_id": "c-no-span",
                "document_id": "d",
                "snippet": "no span",
                "evidence_start_char": None,
                "evidence_end_char": None,
                "relevance_score": 0.9,
            }
        ]

    monkeypatch.setattr(orch_mod, "build_citations_from_docs", _build_citations, raising=True)

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
            "retrieval_contract_mode": "deterministic_recall",
            "metrics": {},
        }
    )

    assert [citation["chunk_id"] for citation in out.get("citations") or []] == ["c-span"]
    assert out.get("fallback_reason") == "strict_span_empty"

    metrics = out.get("metrics") or {}
    assert metrics.get("hard_fallback_attempted") is True
    assert metrics.get("hard_fallback_used") is True
    assert metrics.get("retrieval_fallback_reason") == "strict_span_empty"
    per_query = metrics.get("retrieval_per_query") or []
    assert [item.get("kind") for item in per_query] == ["main", "hard_fallback"]


def test_orchestrator_query_expansion_budget_reports_degradation(monkeypatch) -> None:  # noqa: ANN001
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
    monkeypatch.setattr(settings, "RAG_ABSTAIN_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_ABSTAIN_MIN_CITATIONS", 0, raising=False)

    monkeypatch.setattr(
        orch_mod,
        "_decompose_query",
        lambda *_args, **_kwargs: (["sub question"], 0.5, None, {"ok": True, "method": "stub", "error": None}),
        raising=True,
    )
    monkeypatch.setattr(orch_mod, "hybrid_retriever", _FallbackRetriever(), raising=True)
    monkeypatch.setattr(
        orch_mod,
        "build_citations_from_docs",
        lambda *_args, **_kwargs: [],
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
            "enable_query_decomposition": True,
            "query_expansion_latency_budget_ms": 1,
            "metrics": {},
        }
    )

    budget = (out.get("metrics") or {}).get("query_expansion_budget") or {}
    assert budget["enabled"] is True
    assert budget["degraded"] is True
    assert "latency_budget_exceeded" in budget["reasons"]
    assert "latency_budget_drop:subq" in budget["reasons"]
    assert int((out.get("metrics") or {}).get("retrieval_query_count") or 0) == 1
