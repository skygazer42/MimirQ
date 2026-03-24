from __future__ import annotations

import pytest


def test_route_intent_marks_greetings_as_no_retrieval() -> None:
    from app.rag.policy.intent_router import route_intent

    out = route_intent("hello")

    assert out["intent"] == "greeting"
    assert out["skip_retrieval"] is True
    assert any(str(reason).startswith("social:") for reason in (out.get("reasons") or []))


def test_orchestrator_skips_retrieval_for_no_retrieval_intent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.retrieval.orchestrator as orch
    from app.core.config import settings

    monkeypatch.setattr(settings, "ENABLE_QUERY_REWRITE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_MULTI_QUERY", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_HYDE", False, raising=False)
    monkeypatch.setattr(settings, "ENABLE_QUERY_DECOMPOSITION", False, raising=False)

    class _ForbiddenRetriever:
        _last_debug_metrics: dict[str, object] = {}

        def model_copy(self, **_kwargs):  # noqa: ANN001, ANN002, ANN003
            return self

        def invoke(self, _query):  # noqa: ANN001
            raise AssertionError("retriever should not be called for no-retrieval intents")

    class _FakeEngine:
        pass

    monkeypatch.setattr(orch, "hybrid_retriever", _ForbiddenRetriever(), raising=True)
    monkeypatch.setattr(orch, "get_rag_engine", lambda: _FakeEngine(), raising=True)

    out = orch.run_retrieval({"question": "hello", "history": []})

    assert out.get("docs") == []
    assert out.get("citations") == []
    assert out.get("abstain_triggered") is False

    metrics = out.get("metrics") or {}
    assert metrics.get("retrieval_bypassed") is True
    assert metrics.get("retrieval_bypass_reason") == "no_retrieval_intent"
    assert metrics.get("retrieval_bypass_intent") == "greeting"

    query_debug = out.get("query_debug") or {}
    no_retrieval_intent = query_debug.get("no_retrieval_intent") or {}
    assert no_retrieval_intent.get("intent") == "greeting"
    assert no_retrieval_intent.get("skip_retrieval") is True
