from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException


def _patch_minimal_rag(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings

    # Keep handlers on the lightweight path (no DB existence scan).
    monkeypatch.setattr(settings, "CHAT_ALLOW_EMPTY_DOCUMENTS", True, raising=False)
    monkeypatch.setattr(settings, "CHAT_ALLOW_OPEN_SCOPE", True, raising=False)

    import app.api.v1.rag as rag_api

    # Avoid real dataset membership/permission checks.
    monkeypatch.setattr(rag_api.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)

    # Avoid real retrieval work (vector store, Postgres, etc).
    import app.rag.pipelines.langgraph as langgraph_mod
    import app.rag.retrieval.orchestrator as orch_mod

    monkeypatch.setattr(langgraph_mod, "build_rag_state", lambda **_kwargs: {}, raising=True)
    monkeypatch.setattr(
        orch_mod,
        "run_retrieval",
        lambda *_a, **_k: {"citations": [], "metrics": {}, "query_for_retrieval": "q"},
        raising=True,
    )


@pytest.mark.asyncio
async def test_rag_retrieve_enforces_tenant_qps_quota(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_minimal_rag(monkeypatch)

    import app.api.v1.rag as rag_api
    import app.services.tenant_quota_service as quota_mod

    calls: dict[str, object] = {}

    def _fake_enforce(*, tenant_id, key: str = "chat"):  # noqa: ANN001
        calls["tenant_id"] = tenant_id
        calls["key"] = key
        raise HTTPException(status_code=429, detail="Tenant QPS quota exceeded", headers={"Retry-After": "1"})

    monkeypatch.setattr(quota_mod, "enforce_tenant_qps_quota", _fake_enforce, raising=True)

    body = rag_api.EvidenceRetrieveRequest(query="q")
    with pytest.raises(HTTPException) as excinfo:
        await rag_api.retrieve_evidence(body=body, tenant_id=uuid.uuid4(), account_id="u", db=None)

    assert excinfo.value.status_code == 429
    assert calls.get("key") == "retrieval"


@pytest.mark.asyncio
async def test_rag_retrieve_preview_enforces_tenant_qps_quota(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_minimal_rag(monkeypatch)

    import app.api.v1.rag as rag_api
    import app.services.tenant_quota_service as quota_mod

    calls: dict[str, object] = {}

    def _fake_enforce(*, tenant_id, key: str = "chat"):  # noqa: ANN001
        calls["tenant_id"] = tenant_id
        calls["key"] = key
        raise HTTPException(status_code=429, detail="Tenant QPS quota exceeded")

    monkeypatch.setattr(quota_mod, "enforce_tenant_qps_quota", _fake_enforce, raising=True)

    body = rag_api.RetrievePreviewRequest(query="q")
    with pytest.raises(HTTPException) as excinfo:
        await rag_api.retrieve_preview(body=body, tenant_id=uuid.uuid4(), account_id="u", db=None)

    assert excinfo.value.status_code == 429
    assert calls.get("key") == "retrieval"


@pytest.mark.asyncio
async def test_rag_retrieve_attaches_quota_meta_to_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_minimal_rag(monkeypatch)

    import app.api.v1.rag as rag_api
    import app.services.tenant_quota_service as quota_mod

    def _fake_enforce(*, tenant_id, key: str = "chat"):  # noqa: ANN001
        return {"enabled": True, "mode": "block", "allowed": True, "retry_after": 0.0, "key": key, "tenant_id": str(tenant_id)}

    monkeypatch.setattr(quota_mod, "enforce_tenant_qps_quota", _fake_enforce, raising=True)

    body = rag_api.EvidenceRetrieveRequest(query="q")
    res = await rag_api.retrieve_evidence(body=body, tenant_id=uuid.uuid4(), account_id="u", db=None)

    meta = (res.metrics or {}).get("tenant_qps_quota") or {}
    assert meta.get("enabled") is True
    assert meta.get("allowed") is True
    assert meta.get("key") == "retrieval"
