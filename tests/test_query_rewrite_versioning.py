from __future__ import annotations

import uuid

import pytest
from langchain_core.documents import Document


class _FakeRetriever:
    def __init__(self, *, docs: list[Document]) -> None:
        self._docs = list(docs)
        self._last_debug_metrics: dict = {}
        self.last_update: dict = {}
        self.sparse_enabled = False
        self.sparse_provider = "deterministic"

    def model_copy(self, **kwargs):  # noqa: ANN001, ANN002, ANN003
        clone = _FakeRetriever(docs=self._docs)
        clone._last_debug_metrics = dict(self._last_debug_metrics)
        update = dict(kwargs.get("update") or {})
        clone.last_update = update
        for key, value in update.items():
            setattr(clone, key, value)
        return clone

    def invoke(self, _q: str):  # noqa: ANN001
        return list(self._docs)


def _patch_orchestrator_deterministic(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Keep orchestrator execution deterministic/offline for hashing/trace tests.

    In particular:
    - no LLM-dependent query transforms should run (history stays empty)
    - disable KG work and dictionary expansion side-effects
    """
    import app.rag.retrieval.orchestrator as orch_mod
    from app.core.config import settings

    # Deterministic: disable optional/LLM-dependent transforms (query rewrite will be enabled in tests
    # but won't execute because history is empty).
    monkeypatch.setattr(settings, "ENABLE_MULTI_QUERY", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_HYDE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_QUERY_DECOMPOSITION", False, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_QUERY_PARALLELISM", 1, raising=False)

    # Keep channel toggles stable for hashing.
    monkeypatch.setattr(settings, "VECTOR_BACKEND", "faiss", raising=False)
    monkeypatch.setattr(settings, "BM25_INDEX_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "LEXICAL_DB_TRGM_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "SPARSE_RETRIEVAL_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "SPARSE_RETRIEVAL_INDEX_PERSIST_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "COLBERT_RETRIEVAL_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "COLBERT_RETRIEVAL_PROVIDER", "deterministic", raising=False)
    monkeypatch.setattr(settings, "COLBERT_RETRIEVAL_INDEX_PERSIST_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_PARENT_CHILD_AUTO_MERGE_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_RERANKER", False, raising=False)
    monkeypatch.setattr(settings, "EVIDENCE_POST_RERANK_ENABLED", False, raising=False)

    # Avoid KG work.
    monkeypatch.setattr(settings, "KG_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "KG_CHAT_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_CHUNK_INJECTION_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "RAG_KG_QUERY_EXPANSION_ENABLED", False, raising=False)

    # Avoid dict expansion interfering with trace/config.
    import app.query.expand as expand_mod

    monkeypatch.setattr(expand_mod, "load_base_dictionary_rules", lambda: [], raising=True)
    monkeypatch.setattr(
        expand_mod,
        "generate_dictionary_expansions",
        lambda **_k: ([], {"enabled": False, "used": False}),
        raising=True,
    )

    doc_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    retriever = _FakeRetriever(
        docs=[
            Document(
                page_content="hit",
                id=str(chunk_id),
                metadata={
                    "document_id": str(doc_id),
                    "chunk_id": str(chunk_id),
                    "chunk_index": 0,
                    "source": "t.md",
                    "score": 0.9,
                },
            )
        ]
    )
    monkeypatch.setattr(orch_mod, "hybrid_retriever", retriever, raising=True)


def test_retrieval_config_hash_changes_when_query_rewrite_strategy_changes(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.retrieval.orchestrator as orch_mod
    from app.core.config import settings

    _patch_orchestrator_deterministic(monkeypatch)

    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", True, raising=False)
    monkeypatch.setattr(settings, "QUERY_REWRITE_STRATEGY", "kb_followup.v1", raising=False)

    base_state = {
        "question": "q",
        "history": [],  # critical: avoid LLM call
        "tenant_id": str(uuid.uuid4()),
        "account_id": "u",
        "dataset_id": None,
        "document_ids": [str(uuid.uuid4())],
        "top_k": 5,
        "score_threshold": 0.0,
        "retrieval_mode": "vector",
        "alpha": 0.6,
        "metrics": {},
    }

    out1 = orch_mod.run_retrieval(dict(base_state))
    h1 = (out1.get("metrics") or {}).get("retrieval_config_hash")
    assert isinstance(h1, str) and len(h1) >= 16

    monkeypatch.setattr(settings, "QUERY_REWRITE_STRATEGY", "kb_followup.v2", raising=False)
    out2 = orch_mod.run_retrieval(dict(base_state))
    h2 = (out2.get("metrics") or {}).get("retrieval_config_hash")
    assert isinstance(h2, str) and len(h2) >= 16

    assert h2 != h1


def test_retrieval_trace_rewrite_includes_strategy_id_and_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.retrieval.orchestrator as orch_mod
    from app.core.config import settings

    _patch_orchestrator_deterministic(monkeypatch)

    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", True, raising=False)
    monkeypatch.setattr(settings, "QUERY_REWRITE_STRATEGY", "kb_followup.v1", raising=False)

    out = orch_mod.run_retrieval(
        {
            "question": "q",
            "history": [],  # critical: avoid LLM call
            "tenant_id": str(uuid.uuid4()),
            "account_id": "u",
            "dataset_id": None,
            "document_ids": [str(uuid.uuid4())],
            "top_k": 5,
            "retrieval_mode": "vector",
            "metrics": {},
        }
    )

    trace = out.get("retrieval_trace")
    assert isinstance(trace, dict)
    rewrite = trace.get("rewrite")
    assert isinstance(rewrite, dict)

    # New PII-safe, versioned strategy identifiers.
    assert rewrite.get("strategy_id") == "kb_followup.v1"
    strategy_hash = rewrite.get("strategy_hash")
    assert isinstance(strategy_hash, str) and len(strategy_hash) >= 8


def test_regression_leaderboard_config_hash_includes_query_rewrite_strategy(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings
    from app.services import regression_leaderboard as lb_mod

    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", True, raising=False)
    monkeypatch.setattr(settings, "QUERY_REWRITE_STRATEGY", "kb_followup.v1", raising=False)

    rag_params = {
        "top_k": 20,
        "score_threshold": 0.0,
        "retrieval_mode": "hybrid",
        "alpha": 0.6,
        "enable_weight_rerank": True,
        "vector_weight": 0.6,
        "keyword_weight": 0.4,
        "mmr_lambda": 0.7,
        "enable_reranker": False,
        "reranker_provider": "llm",
        "reranker_top_n": 20,
    }

    h1 = lb_mod._build_run_retrieval_config_hash(rag_params=rag_params)
    assert isinstance(h1, str) and len(h1) >= 16

    monkeypatch.setattr(settings, "QUERY_REWRITE_STRATEGY", "kb_followup.v2", raising=False)
    h2 = lb_mod._build_run_retrieval_config_hash(rag_params=rag_params)
    assert isinstance(h2, str) and len(h2) >= 16
    assert h2 != h1


def test_run_retrieval_honors_runtime_query_rewrite_override(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.retrieval.orchestrator as orch_mod
    from app.core.config import settings

    _patch_orchestrator_deterministic(monkeypatch)

    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", False, raising=False)
    monkeypatch.setattr(settings, "QUERY_REWRITE_STRATEGY", "kb_followup.v1", raising=False)

    base_state = {
        "question": "q",
        "history": [],
        "tenant_id": str(uuid.uuid4()),
        "account_id": "u",
        "dataset_id": None,
        "document_ids": [str(uuid.uuid4())],
        "top_k": 5,
        "score_threshold": 0.0,
        "retrieval_mode": "vector",
        "metrics": {},
    }

    out_disabled = orch_mod.run_retrieval(dict(base_state))
    assert (out_disabled.get("metrics") or {}).get("query_rewrite_enabled") is False

    out_enabled = orch_mod.run_retrieval(
        {
            **base_state,
            "enable_query_rewrite": True,
            "query_rewrite_strategy": "kb_followup.v2",
            "query_rewrite_temperature": 0.3,
            "query_rewrite_max_chars": 180,
        }
    )

    assert (out_enabled.get("metrics") or {}).get("query_rewrite_enabled") is True
    assert ((out_enabled.get("retrieval_trace") or {}).get("rewrite") or {}).get("strategy_id") == "kb_followup.v2"
    assert (out_enabled.get("metrics") or {}).get("retrieval_config_hash") != (
        out_disabled.get("metrics") or {}
    ).get("retrieval_config_hash")


def test_run_retrieval_passes_sparse_runtime_overrides_to_retriever(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.retrieval.orchestrator as orch_mod

    _patch_orchestrator_deterministic(monkeypatch)

    out = orch_mod.run_retrieval(
        {
            "question": "q",
            "history": [],
            "tenant_id": str(uuid.uuid4()),
            "account_id": "u",
            "dataset_id": None,
            "document_ids": [str(uuid.uuid4())],
            "top_k": 5,
            "score_threshold": 0.0,
            "retrieval_mode": "vector",
            "sparse_retrieval_enabled": True,
            "sparse_retrieval_provider": "splade",
            "metrics": {},
        }
    )

    cfg = (((out.get("retrieval_trace") or {}).get("retrieval_config") or {}).get("config") or {})
    assert cfg.get("sparse_enabled") is True
    assert cfg.get("sparse_provider") == "splade"
