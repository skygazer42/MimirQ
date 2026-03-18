from __future__ import annotations

from typing import Any

import pytest


def test_corrective_loop_disabled_runs_once(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings
    from app.rag.pipelines.langgraph import _run_corrective_loop

    monkeypatch.setattr(settings, "RAG_CORRECTIVE_ENABLED", False, raising=False)

    calls: list[tuple[str, Any]] = []

    def retrieve_fn(state: dict[str, Any]) -> dict[str, Any]:
        calls.append(("retrieve", state.get("retrieval_profile")))
        return {**state, "abstain_triggered": False, "metrics": dict(state.get("metrics") or {})}

    def generate_fn(state: dict[str, Any]) -> dict[str, Any]:
        calls.append(("generate", None))
        m = dict(state.get("metrics") or {})
        m["faithfulness_score"] = 0.9
        return {**state, "answer": "ok", "metrics": m}

    out = _run_corrective_loop(
        {"question": "q", "metrics": {}},
        retrieve_fn=retrieve_fn,
        generate_fn=generate_fn,
    )

    assert out.get("answer") == "ok"
    assert [c[0] for c in calls] == ["retrieve", "generate"]


def test_corrective_loop_retries_on_abstain(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings
    from app.rag.pipelines.langgraph import _run_corrective_loop

    monkeypatch.setattr(settings, "RAG_CORRECTIVE_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RAG_CORRECTIVE_MAX_ATTEMPTS", 2, raising=False)
    monkeypatch.setattr(settings, "RAG_CORRECTIVE_MIN_FAITHFULNESS_SCORE", 0.75, raising=False)
    monkeypatch.setattr(settings, "RAG_CORRECTIVE_SECOND_PASS_PROFILE", "recall50", raising=False)
    monkeypatch.setattr(settings, "RAG_CORRECTIVE_SECOND_PASS_ENABLE_MULTI_QUERY", True, raising=False)
    monkeypatch.setattr(settings, "RAG_CORRECTIVE_SECOND_PASS_MULTI_QUERY_COUNT", 5, raising=False)
    monkeypatch.setattr(settings, "MULTI_QUERY_COUNT_CAP", 8, raising=False)

    passed_profiles: list[str | None] = []
    passed_mq: list[tuple[bool | None, int | None]] = []
    retrieve_calls = 0

    def retrieve_fn(state: dict[str, Any]) -> dict[str, Any]:
        nonlocal retrieve_calls
        retrieve_calls += 1
        passed_profiles.append(state.get("retrieval_profile"))
        passed_mq.append((state.get("enable_multi_query"), state.get("multi_query_count")))
        # First attempt abstains; second attempt succeeds.
        abstain = retrieve_calls == 1
        m = dict(state.get("metrics") or {})
        m["retrieval_mode"] = "hybrid"
        return {
            **state,
            "retrieval_profile": state.get("retrieval_profile"),
            "abstain_triggered": abstain,
            "metrics": m,
        }

    def generate_fn(state: dict[str, Any]) -> dict[str, Any]:
        m = dict(state.get("metrics") or {})
        m["faithfulness_score"] = 0.9
        return {**state, "answer": "ok", "metrics": m}

    out = _run_corrective_loop(
        {"question": "q", "metrics": {}, "retrieval_profile": None},
        retrieve_fn=retrieve_fn,
        generate_fn=generate_fn,
    )

    assert out.get("answer") == "ok"
    assert retrieve_calls == 2

    # Second attempt should switch to recall50 and force-enable multi-query.
    assert passed_profiles[1] == "recall50"
    assert passed_mq[1][0] is True
    assert passed_mq[1][1] == 5

    metrics = out.get("metrics") or {}
    assert metrics.get("corrective_enabled") is True
    assert metrics.get("corrective_used") is True
    assert "abstain" in (metrics.get("corrective_reason_codes") or [])


def test_corrective_loop_retries_on_low_faithfulness(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings
    from app.rag.pipelines.langgraph import _run_corrective_loop

    monkeypatch.setattr(settings, "RAG_CORRECTIVE_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RAG_CORRECTIVE_MAX_ATTEMPTS", 2, raising=False)
    monkeypatch.setattr(settings, "RAG_CORRECTIVE_MIN_FAITHFULNESS_SCORE", 0.8, raising=False)
    monkeypatch.setattr(settings, "RAG_CORRECTIVE_SECOND_PASS_PROFILE", "recall50", raising=False)
    monkeypatch.setattr(settings, "RAG_CORRECTIVE_SECOND_PASS_ENABLE_MULTI_QUERY", False, raising=False)

    attempt = 0

    def retrieve_fn(state: dict[str, Any]) -> dict[str, Any]:
        m = dict(state.get("metrics") or {})
        m["retrieval_mode"] = "hybrid"
        return {**state, "abstain_triggered": False, "metrics": m}

    def generate_fn(state: dict[str, Any]) -> dict[str, Any]:
        nonlocal attempt
        attempt += 1
        m = dict(state.get("metrics") or {})
        # First attempt: low faithfulness, second attempt: high.
        m["faithfulness_score"] = 0.5 if attempt == 1 else 0.95
        return {**state, "answer": f"ok-{attempt}", "metrics": m}

    out = _run_corrective_loop(
        {"question": "q", "metrics": {}, "retrieval_profile": None},
        retrieve_fn=retrieve_fn,
        generate_fn=generate_fn,
    )

    assert out.get("answer") == "ok-2"
    metrics = out.get("metrics") or {}
    assert metrics.get("corrective_used") is True
    assert "faithfulness_lt_min" in (metrics.get("corrective_reason_codes") or [])

