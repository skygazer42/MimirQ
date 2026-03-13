from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.tenant import get_tenant_id
from app.core.config import settings


def _build_app() -> TestClient:
    app = FastAPI()

    @app.get("/tid")
    def get_tid(*, tenant_id: Annotated[uuid.UUID, Depends(get_tenant_id)]):  # noqa: B008
        return {"tenant_id": str(tenant_id)}

    return TestClient(app)


def test_get_tenant_id_accepts_custom_tenant_header(monkeypatch):
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setattr(settings, "TENANT_HEADER", "X-Workspace-ID", raising=False)

    client = _build_app()
    tenant_id = uuid.uuid4()

    res = client.get("/tid", headers={"X-Workspace-ID": str(tenant_id)})
    assert res.status_code == 200
    assert res.json()["tenant_id"] == str(tenant_id)


def test_get_tenant_id_still_accepts_x_tenant_id_header_when_overridden(monkeypatch):
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setattr(settings, "TENANT_HEADER", "X-Workspace-ID", raising=False)

    client = _build_app()
    tenant_id = uuid.uuid4()

    res = client.get("/tid", headers={"X-Tenant-ID": str(tenant_id)})
    assert res.status_code == 200
    assert res.json()["tenant_id"] == str(tenant_id)

