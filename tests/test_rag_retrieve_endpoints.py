from __future__ import annotations

import uuid

import pytest


@pytest.mark.asyncio
async def test_rag_retrieve_passes_must_recall_fields_into_rag_state(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.rag as rag_api
    from app.api.schemas.chat import ChatRAGConfig
    from app.core.config import settings

    monkeypatch.setattr(settings, "CHAT_ALLOW_EMPTY_DOCUMENTS", True, raising=False)
    monkeypatch.setattr(settings, "CHAT_ALLOW_OPEN_SCOPE", True, raising=False)
    monkeypatch.setattr(rag_api.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)

    captured: dict = {}

    def _build_rag_state(**kwargs):  # noqa: ANN003
        captured.update(kwargs)
        return {}

    def _retrieve_node(_state):  # noqa: ANN001
        return {"citations": [], "metrics": {}, "query_for_retrieval": "q"}

    import app.rag.pipelines.langgraph as lg_mod
    import app.rag.retrieval.orchestrator as orch_mod

    monkeypatch.setattr(lg_mod, "build_rag_state", _build_rag_state, raising=True)
    monkeypatch.setattr(orch_mod, "run_retrieval", _retrieve_node, raising=True)

    body = rag_api.EvidenceRetrieveRequest(
        query="q",
        rag_config=ChatRAGConfig(
            retrieval_contract_mode="must_recall_strict",
            must_recall=True,
            must_recall_expected_source_keys=["inventory", "users"],
            must_recall_required_anchor_fields=["chunk_id", "document_id"],
        ),
    )
    response = await rag_api.retrieve_evidence(
        body=body,
        tenant_id=uuid.uuid4(),
        account_id="u",
        db=None,
    )

    assert captured.get("retrieval_contract_mode") == "must_recall_strict"
    assert captured.get("must_recall") is True
    assert list(captured.get("must_recall_expected_source_keys") or []) == ["inventory", "users"]
    assert list(captured.get("must_recall_required_anchor_fields") or []) == ["chunk_id", "document_id"]
    capsule = response.evidence_capsule or {}
    assert str(capsule.get("schema") or "") == "mimirq.evidence_capsule.v1"
    assert str(capsule.get("capsule_hash") or "")
