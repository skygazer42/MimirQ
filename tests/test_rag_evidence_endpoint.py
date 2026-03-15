import uuid

import pytest


@pytest.mark.asyncio
async def test_rag_retrieve_defaults_to_recall50_when_rag_config_omitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    The production retrieval-only endpoint should be recall-first by default.

    We keep this unit-level by monkeypatching the graph entrypoints.
    """
    from app.core.config import settings

    # Keep the handler on the lightweight path (no DB existence scan).
    monkeypatch.setattr(settings, "CHAT_ALLOW_EMPTY_DOCUMENTS", True, raising=False)
    monkeypatch.setattr(settings, "CHAT_ALLOW_OPEN_SCOPE", True, raising=False)

    import app.api.v1.rag as rag_api

    monkeypatch.setattr(rag_api.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)

    captured: dict = {}

    def _build_rag_state(**kwargs):  # noqa: ANN003
        captured.update(kwargs)
        return {}

    def _retrieve_node(_state):  # noqa: ANN001
        return {
            "citations": [],
            "metrics": {},
            "query_for_retrieval": captured.get("question") or "",
        }

    import app.rag.pipelines.langgraph as lg_mod
    import app.rag.retrieval.orchestrator as orch_mod

    monkeypatch.setattr(lg_mod, "build_rag_state", _build_rag_state, raising=True)
    monkeypatch.setattr(orch_mod, "run_retrieval", _retrieve_node, raising=True)

    body = rag_api.EvidenceRetrieveRequest(query="q")
    await rag_api.retrieve_evidence(
        body=body,
        tenant_id=uuid.uuid4(),
        account_id="u",
        db=None,
    )

    assert int(captured.get("top_k") or 0) >= 50
    score_threshold = captured.get("score_threshold")
    assert score_threshold is not None
    assert float(score_threshold) == pytest.approx(0.0)
    assert captured.get("retrieval_profile") == "recall50"


@pytest.mark.asyncio
async def test_rag_retrieve_includes_schema_identifier(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "CHAT_ALLOW_EMPTY_DOCUMENTS", True, raising=False)
    monkeypatch.setattr(settings, "CHAT_ALLOW_OPEN_SCOPE", True, raising=False)

    import app.api.v1.rag as rag_api

    monkeypatch.setattr(rag_api.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)

    def _build_rag_state(**_kwargs):  # noqa: ANN003
        return {}

    def _retrieve_node(_state):  # noqa: ANN001
        return {"citations": [], "metrics": {}, "query_for_retrieval": "q"}

    import app.rag.pipelines.langgraph as lg_mod
    import app.rag.retrieval.orchestrator as orch_mod

    monkeypatch.setattr(lg_mod, "build_rag_state", _build_rag_state, raising=True)
    monkeypatch.setattr(orch_mod, "run_retrieval", _retrieve_node, raising=True)

    body = rag_api.EvidenceRetrieveRequest(query="q")
    res = await rag_api.retrieve_evidence(
        body=body,
        tenant_id=uuid.uuid4(),
        account_id="u",
        db=None,
    )

    assert res.schema == "mimirq.evidence.v1"


@pytest.mark.asyncio
async def test_rag_retrieve_sets_has_evidence_when_citations_present(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "CHAT_ALLOW_EMPTY_DOCUMENTS", True, raising=False)
    monkeypatch.setattr(settings, "CHAT_ALLOW_OPEN_SCOPE", True, raising=False)

    import app.api.v1.rag as rag_api

    monkeypatch.setattr(rag_api.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)

    def _build_rag_state(**_kwargs):  # noqa: ANN003
        return {}

    def _retrieve_node(_state):  # noqa: ANN001
        return {
            "citations": [{"chunk_id": "c1"}],
            "metrics": {"abstain_triggered": False},
            "query_for_retrieval": "q",
        }

    import app.rag.pipelines.langgraph as lg_mod
    import app.rag.retrieval.orchestrator as orch_mod

    monkeypatch.setattr(lg_mod, "build_rag_state", _build_rag_state, raising=True)
    monkeypatch.setattr(orch_mod, "run_retrieval", _retrieve_node, raising=True)

    body = rag_api.EvidenceRetrieveRequest(query="q")
    res = await rag_api.retrieve_evidence(
        body=body,
        tenant_id=uuid.uuid4(),
        account_id="u",
        db=None,
    )

    assert bool(res.has_evidence) is True


@pytest.mark.asyncio
async def test_rag_retrieve_has_evidence_respects_min_top_relevance_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "CHAT_ALLOW_EMPTY_DOCUMENTS", True, raising=False)
    monkeypatch.setattr(settings, "CHAT_ALLOW_OPEN_SCOPE", True, raising=False)
    # When enabled (>0), has_evidence should require top_relevance_score >= min.
    monkeypatch.setattr(settings, "RAG_ABSTAIN_MIN_TOP_RELEVANCE_SCORE", 0.5, raising=False)

    import app.api.v1.rag as rag_api

    monkeypatch.setattr(rag_api.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)

    def _build_rag_state(**_kwargs):  # noqa: ANN003
        return {}

    def _retrieve_node(_state):  # noqa: ANN001
        return {
            "citations": [{"chunk_id": "c1"}],
            "metrics": {"abstain_triggered": False, "top_relevance_score": 0.1},
            "query_for_retrieval": "q",
        }

    import app.rag.pipelines.langgraph as lg_mod
    import app.rag.retrieval.orchestrator as orch_mod

    monkeypatch.setattr(lg_mod, "build_rag_state", _build_rag_state, raising=True)
    monkeypatch.setattr(orch_mod, "run_retrieval", _retrieve_node, raising=True)

    body = rag_api.EvidenceRetrieveRequest(query="q")
    res = await rag_api.retrieve_evidence(
        body=body,
        tenant_id=uuid.uuid4(),
        account_id="u",
        db=None,
    )

    assert bool(res.has_evidence) is False


@pytest.mark.asyncio
async def test_rag_retrieve_iterative_fallback_selects_fallback_when_primary_has_no_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "CHAT_ALLOW_EMPTY_DOCUMENTS", True, raising=False)
    monkeypatch.setattr(settings, "CHAT_ALLOW_OPEN_SCOPE", True, raising=False)

    monkeypatch.setattr(settings, "EVIDENCE_ITERATIVE_RETRIEVE_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "EVIDENCE_ITERATIVE_RETRIEVE_MAX_PASSES", 2, raising=False)
    monkeypatch.setattr(settings, "EVIDENCE_ITERATIVE_RETRIEVE_FALLBACK_PROFILE", "coverage80", raising=False)
    monkeypatch.setattr(settings, "EVIDENCE_ITERATIVE_RETRIEVE_FALLBACK_MODE", "keyword", raising=False)

    import app.api.v1.rag as rag_api

    monkeypatch.setattr(rag_api.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)

    def _build_rag_state(**_kwargs):  # noqa: ANN003
        return {"question": "q", "retrieval_profile": None, "retrieval_mode": "hybrid", "top_k": 5, "score_threshold": 0.7}

    calls: list[dict] = []

    def _fake_run_retrieval(state):  # noqa: ANN001
        calls.append(dict(state or {}))
        profile = str((state or {}).get("retrieval_profile") or "").strip().lower()
        if profile == "coverage80":
            return {
                "citations": [{"chunk_id": "c1"}],
                "metrics": {"abstain_triggered": False, "top_relevance_score": 0.9, "retrieval_mode": "keyword"},
                "query_for_retrieval": "q_fallback",
                "query_debug": {"original": "q"},
            }
        return {
            "citations": [],
            "metrics": {
                "abstain_triggered": False,
                "top_relevance_score": 0.0,
                "retrieval_mode": "hybrid",
                "empty_retrieval": {
                    "reasons": ["metadata_filter"],
                    "signals": {"filtered_metadata_filter": 3},
                },
            },
            "query_for_retrieval": "q_primary",
            "query_debug": {"original": "q"},
        }

    import app.rag.pipelines.langgraph as lg_mod
    import app.rag.retrieval.orchestrator as orch_mod

    monkeypatch.setattr(lg_mod, "build_rag_state", _build_rag_state, raising=True)
    monkeypatch.setattr(orch_mod, "run_retrieval", _fake_run_retrieval, raising=True)

    body = rag_api.EvidenceRetrieveRequest(query="q")
    res = await rag_api.retrieve_evidence(
        body=body,
        tenant_id=uuid.uuid4(),
        account_id="u",
        db=None,
    )

    assert bool(res.has_evidence) is True
    assert res.query_for_retrieval == "q_fallback"
    assert len(calls) == 2
    assert str(calls[0].get("retrieval_profile") or "").strip().lower() != "coverage80"
    assert str(calls[1].get("retrieval_profile") or "").strip().lower() == "coverage80"

    dumped = res.model_dump()
    assert (dumped.get("metrics") or {}).get("iterative_retrieve", {}).get("selected_pass") == "fallback"
    passes = (dumped.get("metrics") or {}).get("iterative_retrieve", {}).get("passes") or []
    assert passes
    assert (passes[0] or {}).get("empty_retrieval", {}).get("reasons") == ["metadata_filter"]


@pytest.mark.asyncio
async def test_rag_retrieve_iterative_fallback_disabled_does_not_run_second_pass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "CHAT_ALLOW_EMPTY_DOCUMENTS", True, raising=False)
    monkeypatch.setattr(settings, "CHAT_ALLOW_OPEN_SCOPE", True, raising=False)

    monkeypatch.setattr(settings, "EVIDENCE_ITERATIVE_RETRIEVE_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "EVIDENCE_ITERATIVE_RETRIEVE_MAX_PASSES", 2, raising=False)

    import app.api.v1.rag as rag_api

    monkeypatch.setattr(rag_api.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)

    def _build_rag_state(**_kwargs):  # noqa: ANN003
        return {"question": "q", "retrieval_profile": None, "retrieval_mode": "hybrid", "top_k": 5, "score_threshold": 0.7}

    calls: list[dict] = []

    def _fake_run_retrieval(state):  # noqa: ANN001
        calls.append(dict(state or {}))
        return {
            "citations": [],
            "metrics": {"abstain_triggered": False, "top_relevance_score": 0.0, "retrieval_mode": "hybrid"},
            "query_for_retrieval": "q_primary",
            "query_debug": {"original": "q"},
        }

    import app.rag.pipelines.langgraph as lg_mod
    import app.rag.retrieval.orchestrator as orch_mod

    monkeypatch.setattr(lg_mod, "build_rag_state", _build_rag_state, raising=True)
    monkeypatch.setattr(orch_mod, "run_retrieval", _fake_run_retrieval, raising=True)

    body = rag_api.EvidenceRetrieveRequest(query="q")
    res = await rag_api.retrieve_evidence(
        body=body,
        tenant_id=uuid.uuid4(),
        account_id="u",
        db=None,
    )

    assert bool(res.has_evidence) is False
    assert res.query_for_retrieval == "q_primary"
    assert len(calls) == 1
    assert (res.model_dump().get("metrics") or {}).get("iterative_retrieve") is None
