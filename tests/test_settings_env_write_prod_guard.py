from __future__ import annotations

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db


class _DummyDB:
    def add(self, obj) -> None:  # noqa: ANN001
        return None

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


def test_settings_put_rejected_when_env_write_disabled(monkeypatch, tmp_path):  # noqa: ANN001
    import app.api.v1.settings as settings_module
    from app.api.v1.settings import update_settings
    from app.core.config import settings

    monkeypatch.setattr(settings_module, "_ensure_settings_writable", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(settings_module, "ENV_FILE", tmp_path / "test.env", raising=True)
    monkeypatch.setattr(settings, "SETTINGS_ENV_WRITE_ENABLED", False, raising=False)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.put("/api/v1/settings")(update_settings)
    client = TestClient(app)

    res = client.put("/api/v1/settings", json={})
    assert res.status_code == 403, res.text
    assert not (tmp_path / "test.env").exists()

