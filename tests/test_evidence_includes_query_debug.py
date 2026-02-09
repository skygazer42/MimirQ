import uuid

import pytest


@pytest.mark.asyncio
async def test_rag_retrieve_includes_query_debug_when_present(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "CHAT_ALLOW_EMPTY_DOCUMENTS", True, raising=False)

    import app.api.v1.rag as rag_api

    monkeypatch.setattr(rag_api.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)

    import app.rag.pipelines.langgraph as lg_mod

    monkeypatch.setattr(lg_mod, "build_rag_state", lambda **_k: {}, raising=True)
    monkeypatch.setattr(
        lg_mod,
        "_retrieve_node",
        lambda _state: {
            "citations": [],
            "metrics": {},
            "query_for_retrieval": "q",
            "query_debug": {
                "original": "o",
                "normalized": "n",
                "expansions": [],
                "contributions": [],
            },
        },
        raising=True,
    )

    body = rag_api.EvidenceRetrieveRequest(query="o")
    res = await rag_api.retrieve_evidence(
        body=body,
        tenant_id=uuid.uuid4(),
        account_id="u",
        db=None,
    )

    dumped = res.model_dump()
    assert dumped.get("query_debug", {}).get("original") == "o"

