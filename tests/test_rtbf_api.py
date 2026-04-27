from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db


def _build_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    import app.api.v1.rtbf as rtbf_api

    async def _fake_run_rtbf_cascade(_db, **kwargs):  # noqa: ANN001
        return {
            "schema": "mimirq.rtbf_cascade.v1",
            "tenant_id": str(kwargs["tenant_id"]),
            "subject_account_id": kwargs["subject_account_id"],
            "dry_run": bool(kwargs["dry_run"]),
            "eligible": 2,
            "deleted": 0,
            "errors": 0,
            "cache_invalidations": 0,
            "retried_documents": 0,
            "documents": [],
            "artifact_scopes": ["documents", "chunks", "kg", "vectors", "object_assets", "cache"],
            "ran_at": "2026-04-27T00:00:00+00:00",
        }

    monkeypatch.setattr(rtbf_api, "run_rtbf_cascade", _fake_run_rtbf_cascade, raising=True)

    def _override_get_db():  # noqa: ANN202
        yield object()

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = lambda: uuid.UUID("00000000-0000-0000-0000-000000000001")
    app.dependency_overrides[get_current_account_id] = lambda: "tester"
    app.include_router(rtbf_api.router, prefix="/api/v1/rtbf")
    return TestClient(app)


def test_rtbf_request_endpoint_returns_cascade_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _build_client(monkeypatch)

    res = client.post(
        "/api/v1/rtbf/request",
        json={"subject_account_id": "user-123", "dry_run": True, "max_docs": 10},
    )

    assert res.status_code == 200
    body = res.json()
    assert body["schema"] == "mimirq.rtbf_cascade.v1"
    assert body["subject_account_id"] == "user-123"
    assert body["dry_run"] is True


def test_rtbf_status_endpoint_echoes_ticket_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _build_client(monkeypatch)

    ticket = "rtbf-ticket-001"
    res = client.get(f"/api/v1/rtbf/status/{ticket}")

    assert res.status_code == 200
    body = res.json()
    assert body["ticket_id"] == ticket
    assert body["status"] == "accepted"
