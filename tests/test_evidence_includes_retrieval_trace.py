import uuid

import pytest


@pytest.mark.asyncio
async def test_rag_retrieve_includes_retrieval_trace_when_present(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "CHAT_ALLOW_EMPTY_DOCUMENTS", True, raising=False)
    monkeypatch.setattr(settings, "CHAT_ALLOW_OPEN_SCOPE", True, raising=False)

    import app.api.v1.rag as rag_api

    monkeypatch.setattr(rag_api.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)

    import app.rag.pipelines.langgraph as lg_mod

    monkeypatch.setattr(lg_mod, "build_rag_state", lambda **_k: {}, raising=True)

    import app.rag.retrieval.orchestrator as orch_mod

    monkeypatch.setattr(
        orch_mod,
        "run_retrieval",
        lambda _state: {
            "citations": [],
            "metrics": {},
            "query_for_retrieval": "q",
            "retrieval_trace": {
                "schema": "mimirq.retrieval_trace_pass.v1",
                "retrieval_mode": "vector",
                "requested_retrieval_mode": "vector",
            },
        },
        raising=True,
    )

    body = rag_api.EvidenceRetrieveRequest(query="q")
    res = await rag_api.retrieve_evidence(
        body=body,
        tenant_id=uuid.uuid4(),
        account_id="u",
        db=None,
    )

    dumped = res.model_dump()
    rt = dumped.get("retrieval_trace") or {}
    assert rt.get("schema") == "mimirq.retrieval_trace.v1"
    assert rt.get("selected_pass") == "primary"
    passes = rt.get("passes") or []
    assert passes
    assert passes[0].get("pass") == "primary"
    trace = passes[0].get("trace") or {}
    assert trace.get("schema") == "mimirq.retrieval_trace_pass.v1"

