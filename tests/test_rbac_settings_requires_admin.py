from __future__ import annotations

import uuid

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
    return uuid.uuid4()


def _override_get_current_account_id() -> str:
    return "test-account"


class _Member:
    def __init__(self, role: str):  # noqa: D401
        self.role = role


def test_settings_get_requires_admin_role(monkeypatch):  # noqa: ANN001
    from app.api.v1.settings import get_settings
    from app.services.dataset_service import DatasetService

    monkeypatch.setattr(
        DatasetService,
        "ensure_member",
        lambda *_a, **_k: _Member("viewer"),
        raising=True,
    )

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.get("/api/v1/settings")(get_settings)
    client = TestClient(app)

    res = client.get("/api/v1/settings")
    assert res.status_code == 403, res.text


def test_settings_get_allows_admin_role(monkeypatch):  # noqa: ANN001
    from app.api.v1.settings import get_settings
    from app.services.dataset_service import DatasetService

    monkeypatch.setattr(
        DatasetService,
        "ensure_member",
        lambda *_a, **_k: _Member("admin"),
        raising=True,
    )

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.get("/api/v1/settings")(get_settings)
    client = TestClient(app)

    res = client.get("/api/v1/settings")
    assert res.status_code == 200, res.text
    body = res.json()
    assert isinstance(body, dict)
