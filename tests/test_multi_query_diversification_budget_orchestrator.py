from __future__ import annotations

import json
import uuid

import pytest
from langchain_core.documents import Document
from langchain_core.language_models.fake_chat_models import FakeListChatModel


class _RoutingRetriever:
    def __init__(self, *, main_docs: list[Document], mq_docs: dict[str, list[Document]]) -> None:
        self._main_docs = list(main_docs)
        self._mq_docs = {str(k): list(v) for k, v in (mq_docs or {}).items()}
        self._last_debug_metrics: dict = {}

    def model_copy(self, **_kwargs):  # noqa: ANN001, ANN002, ANN003
        return self

    def invoke(self, q: str):  # noqa: ANN001
        q = (q or "").strip()
        if q == "BASE":
            return list(self._main_docs)
        return list(self._mq_docs.get(q, []))


def _mk_doc(*, doc_id: str, chunk_index: int, family_key: str | None = None, score: float = 1.0) -> Document:
    chunk_id = f"{doc_id}:{chunk_index}"
    return Document(
        page_content=f"{chunk_id} content",
        id=chunk_id,
        metadata={
            "document_id": doc_id,
            "chunk_id": chunk_id,
            "chunk_index": int(chunk_index),
            "source": "t.md",
            "score": float(score),
            "hierarchy_family_key": family_key,
        },
    )


def test_orchestrator_multi_query_diversify_budget_caps_mq_role(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Multi-query can dominate RRF fusion when many mq queries exist.

    When diversification budgeting is enabled, we should cap the number of mq-sourced
    results in the final top_k (rollback is just disabling the setting).
    """
    import app.rag.retrieval.orchestrator as orch_mod
    from app.core.config import settings
    from app.rag.engine import RAGEngine

    # Keep the run offline/deterministic.
    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_HYDE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_QUERY_DECOMPOSITION", False, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_QUERY_PARALLELISM", 1, raising=False)
    monkeypatch.setattr(settings, "KG_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "KG_CHAT_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_CHUNK_INJECTION_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_QUERY_EXPANSION_ENABLED", False, raising=False)

    # Avoid dict expansion.
    import app.query.expand as expand_mod

    monkeypatch.setattr(expand_mod, "load_base_dictionary_rules", lambda: [], raising=True)
    monkeypatch.setattr(
        expand_mod,
        "generate_dictionary_expansions",
        lambda **_k: ([], {"enabled": False, "used": False}),
        raising=True,
    )

    # Enable multi-query with many variants.
    monkeypatch.setattr(settings, "ENABLE_MULTI_QUERY", True, raising=False)
    monkeypatch.setattr(settings, "MULTI_QUERY_COUNT", 5, raising=False)
    monkeypatch.setattr(settings, "MULTI_QUERY_TEMPERATURE", 0.0, raising=False)
    monkeypatch.setattr(settings, "MULTI_QUERY_MAX_CHARS", 200, raising=False)

    # Diversification budget: cap mq contribution in the final top_k.
    monkeypatch.setattr(settings, "MULTI_QUERY_DIVERSIFY_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "MULTI_QUERY_DIVERSIFY_BUDGET", 1, raising=False)

    engine = RAGEngine()
    mq_queries = [f"ALT{i}" for i in range(1, 6)]
    mq_llm = FakeListChatModel(responses=[json.dumps(mq_queries)])
    engine.models["fast"] = mq_llm
    monkeypatch.setattr(orch_mod, "get_rag_engine", lambda: engine, raising=True)

    main_docs = [_mk_doc(doc_id="z-main", chunk_index=i) for i in range(0, 4)]
    mq_docs = {q: [_mk_doc(doc_id=f"a-{q.lower()}", chunk_index=0)] for q in mq_queries}

    retriever = _RoutingRetriever(main_docs=main_docs, mq_docs=mq_docs)
    monkeypatch.setattr(orch_mod, "hybrid_retriever", retriever, raising=True)

    out = orch_mod.run_retrieval(
        {
            "question": "BASE",
            "history": [],
            "tenant_id": str(uuid.uuid4()),
            "account_id": "u",
            "dataset_id": None,
            "document_ids": [str(uuid.uuid4())],
            "top_k": 4,
            "score_threshold": 0.0,
            "retrieval_mode": "vector",
            "metrics": {},
        }
    )

    citations = out.get("citations") or []
    assert len(citations) == 4

    by_role: dict[str, int] = {}
    for c in citations:
        if not isinstance(c, dict):
            continue
        role = str(c.get("retrieval_role") or "main")
        by_role[role] = by_role.get(role, 0) + 1

    # Budget should cap mq role to 1 in the final top_k.
    assert by_role.get("mq", 0) <= 1
    assert by_role.get("main", 0) >= 3


def test_orchestrator_multi_query_diversify_budget_respects_family_aggregation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    When hierarchy family aggregation is enabled, the mq selection should prefer
    families that appear across multiple mq variants (frequency strategy), even
    if their per-variant rank/score is weaker.
    """
    import app.rag.retrieval.orchestrator as orch_mod
    from app.core.config import settings
    from app.rag.engine import RAGEngine

    # Keep the run offline/deterministic.
    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_HYDE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_QUERY_DECOMPOSITION", False, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_QUERY_PARALLELISM", 1, raising=False)
    monkeypatch.setattr(settings, "KG_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "KG_CHAT_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_CHUNK_INJECTION_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_QUERY_EXPANSION_ENABLED", False, raising=False)

    # Avoid dict expansion.
    import app.query.expand as expand_mod

    monkeypatch.setattr(expand_mod, "load_base_dictionary_rules", lambda: [], raising=True)
    monkeypatch.setattr(
        expand_mod,
        "generate_dictionary_expansions",
        lambda **_k: ([], {"enabled": False, "used": False}),
        raising=True,
    )

    # Enable multi-query with many variants + diversification budget.
    monkeypatch.setattr(settings, "ENABLE_MULTI_QUERY", True, raising=False)
    monkeypatch.setattr(settings, "MULTI_QUERY_COUNT", 5, raising=False)
    monkeypatch.setattr(settings, "MULTI_QUERY_TEMPERATURE", 0.0, raising=False)
    monkeypatch.setattr(settings, "MULTI_QUERY_MAX_CHARS", 200, raising=False)
    monkeypatch.setattr(settings, "MULTI_QUERY_DIVERSIFY_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "MULTI_QUERY_DIVERSIFY_BUDGET", 1, raising=False)

    engine = RAGEngine()
    mq_queries = [f"ALT{i}" for i in range(1, 6)]
    mq_llm = FakeListChatModel(responses=[json.dumps(mq_queries)])
    engine.models["fast"] = mq_llm
    monkeypatch.setattr(orch_mod, "get_rag_engine", lambda: engine, raising=True)

    main_docs = [_mk_doc(doc_id="z-main", chunk_index=i) for i in range(0, 4)]

    # Each mq query returns:
    # - a unique family hit (rank 1, high score)
    # - a shared family hit (rank 2, low score) that appears across all mq variants
    mq_docs: dict[str, list[Document]] = {}
    for i, q in enumerate(mq_queries, 1):
        mq_docs[q] = [
            _mk_doc(doc_id=f"u-{i}", chunk_index=0, family_key=f"uniq-{i}", score=1.0),
            _mk_doc(doc_id=f"a-{i}", chunk_index=1, family_key="fam-a", score=0.1),
        ]

    retriever = _RoutingRetriever(main_docs=main_docs, mq_docs=mq_docs)
    monkeypatch.setattr(orch_mod, "hybrid_retriever", retriever, raising=True)

    out = orch_mod.run_retrieval(
        {
            "question": "BASE",
            "history": [],
            "tenant_id": str(uuid.uuid4()),
            "account_id": "u",
            "dataset_id": None,
            "document_ids": [str(uuid.uuid4())],
            "top_k": 4,
            "score_threshold": 0.0,
            "retrieval_mode": "vector",
            "enable_hierarchy_recall": True,
            "hierarchy_family_collapse": True,
            "hierarchy_family_aggregation": "frequency",
            "metrics": {},
        }
    )

    citations = out.get("citations") or []
    mq_citations = [c for c in citations if isinstance(c, dict) and str(c.get("retrieval_role") or "") == "mq"]
    assert len(mq_citations) <= 1
    if mq_citations:
        assert mq_citations[0].get("hierarchy_family_key") == "fam-a"
