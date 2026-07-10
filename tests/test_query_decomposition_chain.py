
from typing import Any

import pytest


def _base_state() -> dict[str, Any]:
    return {
        "question": "complex question",
        "history": [],
        "top_k": 5,
        "score_threshold": 0.0,
        "retrieval_mode": "hybrid",
        "retrieval_profile": None,
        "enable_reranker": False,
        "enable_weight_rerank": False,
        "metrics": {},
    }


def test_run_retrieval_chains_decomposed_queries_sequentially(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.retrieval.orchestrator as orch
    from app.core.config import settings

    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_MULTI_QUERY", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_HYDE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_STEP_BACK_QUERY", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_QUERY_DECOMPOSITION", True, raising=False)
    monkeypatch.setattr(settings, "QUERY_DECOMPOSITION_MIN_CHARS", 0, raising=False)
    monkeypatch.setattr(settings, "QUERY_DECOMPOSITION_MAX_CHARS", 400, raising=False)
    monkeypatch.setattr(settings, "RAG_DECOMPOSITION_CHAIN_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_QUERY_PARALLELISM", 1, raising=False)

    captured_queries: list[str] = []

    class _Retriever:
        _last_debug_metrics: dict[str, Any] = {}

        def model_copy(self, **_kwargs):  # noqa: ANN001, ANN002, ANN003
            return self

        def invoke(self, query):  # noqa: ANN001
            captured_queries.append(str(query))
            return []

    class _FakeEngine:
        def _annotate_docs_with_role(self, docs, _kind):  # noqa: ANN001
            return docs

        def fuse_docs_rrf(self, docs_by_query, rrf_k=60, meta_prefix="query_expansion"):  # noqa: ANN001, ARG002
            out = []
            for ds in docs_by_query or []:
                out.extend(list(ds or []))
            return out

    monkeypatch.setattr(orch, "hybrid_retriever", _Retriever(), raising=True)
    monkeypatch.setattr(orch, "get_rag_engine", lambda: _FakeEngine(), raising=True)
    monkeypatch.setattr(orch, "_decompose_query", lambda *args, **kwargs: ["subquestion one", "subquestion two"], raising=False)

    orch.run_retrieval(_base_state())

    assert len(captured_queries) >= 2
    assert "subquestion one" in captured_queries[0]
    assert "subquestion one" in captured_queries[1]


def test_run_retrieval_marks_decomposition_chain_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.retrieval.orchestrator as orch
    from app.core.config import settings

    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_MULTI_QUERY", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_HYDE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_STEP_BACK_QUERY", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_QUERY_DECOMPOSITION", True, raising=False)
    monkeypatch.setattr(settings, "QUERY_DECOMPOSITION_MIN_CHARS", 0, raising=False)
    monkeypatch.setattr(settings, "QUERY_DECOMPOSITION_MAX_CHARS", 400, raising=False)
    monkeypatch.setattr(settings, "RAG_DECOMPOSITION_CHAIN_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RETRIEVAL_QUERY_PARALLELISM", 1, raising=False)

    class _Retriever:
        _last_debug_metrics: dict[str, Any] = {}

        def model_copy(self, **_kwargs):  # noqa: ANN001, ANN002, ANN003
            return self

        def invoke(self, _query):  # noqa: ANN001
            return []

    class _FakeEngine:
        def _annotate_docs_with_role(self, docs, _kind):  # noqa: ANN001
            return docs

        def fuse_docs_rrf(self, docs_by_query, rrf_k=60, meta_prefix="query_expansion"):  # noqa: ANN001, ARG002
            out = []
            for ds in docs_by_query or []:
                out.extend(list(ds or []))
            return out

    monkeypatch.setattr(orch, "hybrid_retriever", _Retriever(), raising=True)
    monkeypatch.setattr(orch, "get_rag_engine", lambda: _FakeEngine(), raising=True)
    monkeypatch.setattr(orch, "_decompose_query", lambda *args, **kwargs: ["subquestion one", "subquestion two"], raising=False)

    out = orch.run_retrieval(_base_state())

    metrics = out.get("metrics") or {}
    assert metrics.get("decompose_chain_used") is True
