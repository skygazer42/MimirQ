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

    monkeypatch.setattr(lg_mod, "build_rag_state", _build_rag_state, raising=True)
    monkeypatch.setattr(lg_mod, "_retrieve_node", _retrieve_node, raising=True)

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
    assert float(score_threshold) == 0.0
    assert captured.get("retrieval_profile") == "recall50"


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

    monkeypatch.setattr(lg_mod, "build_rag_state", _build_rag_state, raising=True)
    monkeypatch.setattr(lg_mod, "_retrieve_node", _retrieve_node, raising=True)

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

    monkeypatch.setattr(lg_mod, "build_rag_state", _build_rag_state, raising=True)
    monkeypatch.setattr(lg_mod, "_retrieve_node", _retrieve_node, raising=True)

    body = rag_api.EvidenceRetrieveRequest(query="q")
    res = await rag_api.retrieve_evidence(
        body=body,
        tenant_id=uuid.uuid4(),
        account_id="u",
        db=None,
    )

    assert bool(res.has_evidence) is False
