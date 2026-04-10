from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db


class _DummyDB:
    pass


def _override_get_db():  # noqa: ANN202
    yield _DummyDB()


def _override_get_tenant_id() -> uuid.UUID:
    return uuid.UUID("00000000-0000-0000-0000-000000000000")


def _override_get_current_account_id() -> str:
    return "test-account"


@pytest.mark.asyncio
async def test_mineru_service_raises_lookup_error_for_missing_batch(monkeypatch):
    from app.services.mineru_service import MinerUService

    svc = MinerUService()

    monkeypatch.setattr(svc, "_ensure_online_enabled", lambda: None)
    monkeypatch.setattr(svc, "_get_headers", lambda: {})

    async def _fake_request_json(_method: str, _url: str, **_kwargs):  # noqa: ANN001
        return {"code": 1, "msg": "task not found or expire"}

    monkeypatch.setattr(svc, "_arequest_json", _fake_request_json)

    with pytest.raises(LookupError, match="task not found or expire"):
        await svc.aget_task_status("invalid")


def test_batch_upload_status_returns_404_for_missing_remote_task(monkeypatch):
    import app.api.v1.documents as documents_module
    from app.services.dataset_service import DatasetService

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id

    monkeypatch.setattr(DatasetService, "ensure_member", lambda _db, _tenant_id, _account_id: object(), raising=True)

    async def _fake_get_task_status(_batch_id: str):  # noqa: ANN001
        raise LookupError("task not found or expire")

    monkeypatch.setattr(documents_module.mineru_service, "aget_task_status", _fake_get_task_status, raising=True)

    app.get("/api/v1/documents/batch-upload/status/{batch_id}")(documents_module.get_batch_task_status)
    client = TestClient(app)

    res = client.get("/api/v1/documents/batch-upload/status/invalid")
    assert res.status_code == 404
    assert res.json() == {"detail": "task not found or expire"}
