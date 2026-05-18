from __future__ import annotations

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db


class _DummyDB:
    pass


class _Member:
    def __init__(self, role: str):  # noqa: D401
        self.role = role
        self.is_active = True
        self.is_current = True


def _override_get_db():  # noqa: ANN202
    yield _DummyDB()


def _override_get_tenant_id() -> uuid.UUID:
    return uuid.uuid4()


def _override_get_current_account_id() -> str:
    return "test-account"


def test_rbac_me_exposes_backend_navigation_visibility_to_normal_members(monkeypatch):  # noqa: ANN001
    from app.api.v1.rbac import get_current_tenant_access
    from app.core.config import settings
    from app.services.dataset_service import DatasetService

    monkeypatch.setattr(
        DatasetService,
        "ensure_member",
        lambda *_a, **_k: _Member("viewer"),
        raising=True,
    )
    monkeypatch.setattr(
        settings,
        "NAVIGATION_USER_VISIBLE_MODULES",
        "knowledgeGraph,reports,invalidModule",
        raising=False,
    )

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.get("/api/v1/rbac/me")(get_current_tenant_access)
    client = TestClient(app)

    res = client.get("/api/v1/rbac/me")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body.get("role") == "viewer"
    assert body.get("permissions") == []
    assert body.get("navigation_user_visible_modules") == ["knowledgeGraph", "reports"]
