from __future__ import annotations

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db


class _DummyDB:
    def commit(self) -> None:
        return None

    def refresh(self, obj) -> None:  # noqa: ANN001
        return None


def _override_get_db():  # noqa: ANN202
    yield _DummyDB()


def _override_get_tenant_id() -> uuid.UUID:
    return uuid.uuid4()


def _override_get_current_account_id() -> str:
    return "test-account"


def _build_client(monkeypatch):  # noqa: ANN001
    from app.api.v1.pipeline import get_governance_profile_resolved
    from app.services.dataset_service import DatasetService

    monkeypatch.setattr(DatasetService, "ensure_member", lambda _db, _tenant_id, _account_id: None, raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id

    app.get("/api/v1/pipeline/governance-profiles/{profile_ref}/resolved")(get_governance_profile_resolved)
    return TestClient(app)


def test_pipeline_governance_profile_resolved_builtin(monkeypatch):  # noqa: ANN001
    client = _build_client(monkeypatch)

    res = client.get("/api/v1/pipeline/governance-profiles/builtin:html_web/resolved")
    assert res.status_code == 200
    body = res.json()

    assert body["profile"]["key"] == "builtin:html_web"
    assert isinstance(body.get("chain"), list) and body["chain"]
    assert body["chain"][-1]["key"] == "builtin:html_web"

    effective = body["effective"]
    patch = effective.get("pipeline_patch") or {}
    assert patch.get("governance_enabled") is True

