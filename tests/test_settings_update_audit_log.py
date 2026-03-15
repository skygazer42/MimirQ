from __future__ import annotations

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db


class _CaptureDB:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.commits: int = 0

    def add(self, obj) -> None:  # noqa: ANN001
        self.added.append(obj)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        return None


def test_settings_put_writes_audit_log_without_secret_values(monkeypatch, tmp_path):  # noqa: ANN001
    import app.api.v1.settings as settings_module
    from app.api.v1.settings import update_settings
    from app.core.config import settings
    from app.models.audit_log import AuditLog

    tenant_id = uuid.uuid4()
    db = _CaptureDB()

    def _override_get_db():  # noqa: ANN202
        yield db

    def _override_get_tenant_id() -> uuid.UUID:
        return tenant_id

    def _override_get_current_account_id() -> str:
        return "test-account"

    # Keep test isolated from RBAC and runtime config mutation.
    monkeypatch.setattr(settings_module, "_ensure_settings_writable", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(settings_module, "_apply_runtime_settings", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(settings_module, "ENV_FILE", tmp_path / "test.env", raising=True)
    monkeypatch.setattr(settings, "SETTINGS_ENV_WRITE_ENABLED", True, raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.put("/api/v1/settings")(update_settings)

    client = TestClient(app)

    secret_value = "super-secret-value"
    res = client.put(
        "/api/v1/settings",
        headers={"X-Request-ID": "r-audit-1"},
        json={"llm": {"api_key": secret_value}},
    )
    assert res.status_code == 200, res.text

    audit_items = [obj for obj in db.added if isinstance(obj, AuditLog)]
    assert len(audit_items) == 1
    item = audit_items[0]

    assert item.tenant_id == tenant_id
    assert item.actor_id == "test-account"
    assert item.request_id == "r-audit-1"
    assert item.action
    assert isinstance(item.details, dict)

    # Only record updated keys, never raw secret values.
    assert "updated_keys" in item.details
    assert "LLM_API_KEY" in item.details["updated_keys"]
    assert secret_value not in str(item.details)

