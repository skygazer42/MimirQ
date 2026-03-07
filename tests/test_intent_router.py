from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List

import pytest


def test_classify_query_intent_basic() -> None:
    from app.rag.policy.intent_router import classify_query_intent

    intent, reasons = classify_query_intent(
        'Traceback (most recent call last):\n  File "x.py", line 1\nTypeError: bad'
    )
    assert intent == "log"
    assert any(r.startswith("log:") for r in reasons)

    intent, _reasons = classify_query_intent("GET /api/v1/users?limit=10 HTTP/1.1")
    assert intent == "api"

    intent, _reasons = classify_query_intent("How to reset password?")
    assert intent == "howto"

    intent, _reasons = classify_query_intent("What is RAG?")
    assert intent == "faq"

    intent, _reasons = classify_query_intent("Tell me about embeddings")
    assert intent == "general"


def test_route_retrieval_preset_log_overrides_are_bounded_and_pii_safe() -> None:
    from app.rag.policy.intent_router import route_retrieval_preset

    overrides, meta = route_retrieval_preset(
        query='Traceback (most recent call last):\n  File "x.py", line 1\nTypeError: bad',
        retrieval_mode="hybrid",
        retrieval_profile=None,
        top_k=5,
        score_threshold=0.7,
        enable_reranker=True,
        enable_weight_rerank=True,
        enable_multi_query=None,
        enable_query_alias_expansion=None,
    )

    assert overrides.get("retrieval_mode") == "keyword"
    assert overrides.get("retrieval_profile") == "recall20"
    assert overrides.get("enable_reranker") is False
    assert overrides.get("enable_weight_rerank") is False
    assert overrides.get("enable_multi_query") is False
    assert overrides.get("enable_query_alias_expansion") is False
    assert int(overrides.get("top_k") or 0) >= 20
    assert float(overrides.get("score_threshold", 1.0)) == 0.0

    assert meta.get("enabled") is True
    assert meta.get("used") is True
    assert meta.get("intent") == "log"
    assert isinstance(meta.get("reasons"), list)
    assert all(isinstance(r, str) and len(r) <= 40 for r in (meta.get("reasons") or []))
    assert all(isinstance(k, str) and len(k) <= 40 for k in (meta.get("overrides") or []))


def test_route_retrieval_preset_applies_policy_rule_without_leaking_patterns() -> None:
    from app.rag.policy.intent_router import route_retrieval_preset

    policy = {
        "schema": "mimirq.intent_router_policy.v1",
        "rules": [
            {
                "rule_id": "comparison_rerank",
                "match_any": ["benchmark", "compare"],
                "overrides": {
                    "enable_reranker": True,
                    "reranker_provider": "colbert",
                    "reranker_top_n": 15,
                    "retrieval_profile": "recall50",
                },
            }
        ],
    }

    overrides, meta = route_retrieval_preset(
        query="benchmark vector vs bm25 compare",
        retrieval_mode="hybrid",
        retrieval_profile=None,
        top_k=10,
        score_threshold=0.2,
        enable_reranker=False,
        enable_weight_rerank=True,
        enable_multi_query=False,
        enable_query_alias_expansion=False,
        intent_router_policy=policy,
    )

    assert overrides.get("enable_reranker") is True
    assert overrides.get("reranker_provider") == "colbert"
    assert overrides.get("reranker_top_n") == 15
    assert overrides.get("retrieval_profile") == "recall50"
    assert meta.get("policy_used") is True
    assert meta.get("policy_rule_ids") == ["comparison_rerank"]
    encoded = json.dumps(meta, ensure_ascii=False)
    assert "benchmark" not in encoded
    assert "compare" not in encoded


def test_orchestrator_applies_intent_router_to_log_queries(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Integration test: orchestrator.run_retrieval should apply intent routing when enabled.

    We intentionally monkeypatch retrieval/LLM components so the test stays fast and deterministic.
    """
    from app.core.config import settings

    monkeypatch.setattr(settings, "RAG_INTENT_ROUTER_ENABLED", True, raising=False)

    # Keep the test deterministic / no LLM calls.
    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_MULTI_QUERY", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_HYDE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_QUERY_DECOMPOSITION", False, raising=False)

    import app.rag.retrieval.orchestrator as orch

    captured_updates: List[Dict[str, Any]] = []

    class _CapturingRetriever:
        _last_debug_metrics: Dict[str, Any] = {}

        def model_copy(self, **kwargs):  # noqa: ANN001, ANN002, ANN003
            captured_updates.append(dict((kwargs or {}).get("update") or {}))
            return self

        def invoke(self, _q):  # noqa: ANN001
            return []

    class _FakeEngine:
        def _annotate_docs_with_role(self, docs, _kind):  # noqa: ANN001
            return docs

        def fuse_docs_rrf(self, docs_by_query, rrf_k=60, meta_prefix="query_expansion"):  # noqa: ANN001, ARG002
            out = []
            for ds in docs_by_query or []:
                out.extend(list(ds or []))
            return out

    monkeypatch.setattr(orch, "hybrid_retriever", _CapturingRetriever(), raising=True)
    monkeypatch.setattr(orch, "get_rag_engine", lambda: _FakeEngine(), raising=True)

    state = {
        "question": 'Traceback (most recent call last):\n  File "x.py", line 1\nTypeError: bad',
        "history": [],
        "top_k": 5,
        "score_threshold": 0.7,
        "retrieval_mode": "hybrid",
        "retrieval_profile": None,
        "enable_reranker": True,
        "enable_weight_rerank": True,
        "enable_multi_query": None,
        "enable_query_alias_expansion": None,
        "query_aliases": None,
        "query_alias_max_queries": None,
    }

    out = orch.run_retrieval(state)

    base_update = next(u for u in captured_updates if "k" in u)
    assert base_update.get("retrieval_mode") == "keyword"
    assert base_update.get("enable_reranker") is False
    assert base_update.get("enable_weight_rerank") is False
    assert int(base_update.get("k") or 0) >= 20
    assert float(base_update.get("score_threshold", 1.0)) == 0.0

    qd = out.get("query_debug") if isinstance(out, dict) else None
    assert isinstance(qd, dict)
    intent_meta = qd.get("intent_router")
    assert isinstance(intent_meta, dict)
    assert intent_meta.get("enabled") is True
    assert intent_meta.get("intent") == "log"


def test_orchestrator_applies_intent_router_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.retrieval.orchestrator as orch

    captured_updates: List[Dict[str, Any]] = []

    class _CapturingRetriever:
        _last_debug_metrics: Dict[str, Any] = {}

        def model_copy(self, **kwargs):  # noqa: ANN001, ANN002, ANN003
            captured_updates.append(dict((kwargs or {}).get("update") or {}))
            return self

        def invoke(self, _q):  # noqa: ANN001
            return []

    class _FakeEngine:
        def _annotate_docs_with_role(self, docs, _kind):  # noqa: ANN001
            return docs

        def fuse_docs_rrf(self, docs_by_query, rrf_k=60, meta_prefix="query_expansion"):  # noqa: ANN001, ARG002
            out = []
            for ds in docs_by_query or []:
                out.extend(list(ds or []))
            return out

    monkeypatch.setattr(orch, "hybrid_retriever", _CapturingRetriever(), raising=True)
    monkeypatch.setattr(orch, "get_rag_engine", lambda: _FakeEngine(), raising=True)

    state = {
        "question": "benchmark vector vs bm25 compare",
        "history": [],
        "top_k": 5,
        "score_threshold": 0.7,
        "retrieval_mode": "hybrid",
        "retrieval_profile": None,
        "enable_reranker": False,
        "enable_weight_rerank": True,
        "enable_multi_query": False,
        "enable_query_alias_expansion": False,
        "intent_router": True,
        "intent_router_policy": {
            "schema": "mimirq.intent_router_policy.v1",
            "rules": [
                {
                    "rule_id": "comparison_rerank",
                    "match_any": ["benchmark", "compare"],
                    "overrides": {
                        "enable_reranker": True,
                        "reranker_provider": "colbert",
                        "reranker_top_n": 15,
                    },
                }
            ],
        },
    }

    out = orch.run_retrieval(state)

    base_update = next(u for u in captured_updates if "k" in u)
    assert base_update.get("enable_reranker") is True
    assert base_update.get("reranker_provider") == "colbert"
    assert base_update.get("reranker_top_n") == 15

    qd = out.get("query_debug") if isinstance(out, dict) else None
    assert isinstance(qd, dict)
    intent_meta = qd.get("intent_router")
    assert isinstance(intent_meta, dict)
    assert intent_meta.get("policy_used") is True
    assert intent_meta.get("policy_rule_ids") == ["comparison_rerank"]


@pytest.mark.asyncio
async def test_rag_engine_applies_intent_router_to_log_queries(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Integration test: engine.stream_chat (non-LangGraph path) should apply intent routing.

    This matters because chat defaults to the LangChain engine path unless `use_graph=true`.
    """
    import app.rag.engine as engine_mod
    from app.core.config import settings

    engine_mod.reset_rag_engine()

    monkeypatch.setattr(settings, "RAG_INTENT_ROUTER_ENABLED", True, raising=False)

    # Keep the test deterministic / no extra LLM calls for expansion.
    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_MULTI_QUERY", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_HYDE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_QUERY_DECOMPOSITION", False, raising=False)

    # Deterministic fake LLM.
    monkeypatch.setattr(settings, "LLM_API_KEY", "", raising=False)
    monkeypatch.setattr(settings, "LLM_MOCK_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "LLM_MOCK_RESPONSE", "OK", raising=False)

    captured_updates: List[Dict[str, Any]] = []

    class _CapturingRetriever:
        _last_debug_metrics: Dict[str, Any] = {}

        def model_copy(self, **kwargs):  # noqa: ANN001, ANN002, ANN003
            captured_updates.append(dict((kwargs or {}).get("update") or {}))
            return self

        def invoke(self, _q):  # noqa: ANN001
            return []

    monkeypatch.setattr(engine_mod, "hybrid_retriever", _CapturingRetriever(), raising=True)
    monkeypatch.setattr(engine_mod, "log_metrics", lambda _p: None, raising=True)

    rag = engine_mod.get_rag_engine()
    agen = rag.stream_chat(
        question='Traceback (most recent call last):\n  File "x.py", line 1\nTypeError: bad',
        history=None,
        conversation_id=None,
        tenant_id=uuid.uuid4(),
        document_ids=None,
        account_id="u",
        top_k=5,
        score_threshold=0.7,
        retrieval_mode="hybrid",
        retrieval_profile=None,
        enable_reranker=True,
        enable_weight_rerank=True,
        db=None,
    )

    done_metrics = None
    async for item in agen:
        if item.get("type") == "done":
            done_metrics = (item.get("data") or {}).get("metrics") or {}
            break
    await agen.aclose()

    base_update = next(u for u in captured_updates if "k" in u)
    assert base_update.get("retrieval_mode") == "keyword"
    assert base_update.get("enable_reranker") is False
    assert base_update.get("enable_weight_rerank") is False
    assert int(base_update.get("k") or 0) >= 20
    assert float(base_update.get("score_threshold", 1.0)) == 0.0

    assert isinstance(done_metrics, dict)
    assert done_metrics.get("intent_router_enabled") is True
    assert done_metrics.get("intent_router_used") is True
