import uuid

import pytest


@pytest.mark.asyncio
async def test_retrieve_preview_defaults_to_recall20_when_rag_config_omitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
        return {"citations": [], "metrics": {}, "query_for_retrieval": captured.get("question") or ""}

    import app.rag.pipelines.langgraph as lg_mod
    import app.rag.retrieval.orchestrator as orch_mod

    monkeypatch.setattr(lg_mod, "build_rag_state", _build_rag_state, raising=True)
    monkeypatch.setattr(orch_mod, "run_retrieval", _retrieve_node, raising=True)

    body = rag_api.RetrievePreviewRequest(query="q")
    await rag_api.retrieve_preview(
        body=body,
        tenant_id=uuid.uuid4(),
        account_id="u",
        db=None,
    )

    assert int(captured.get("top_k") or 0) >= 20
    score_threshold = captured.get("score_threshold")
    assert score_threshold is not None
    assert float(score_threshold) == pytest.approx(0.0)
    assert captured.get("retrieval_profile") == "recall20"
