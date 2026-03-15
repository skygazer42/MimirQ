from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient
from jose import jwt

from app.api.dependencies.auth import get_current_account_id
from app.core.config import settings
from app.models.tenant import Tenant, TenantMember
from app.services.tenant_member_provisioning_service import ensure_tenant_member_for_jwt_user
from tests.helpers.async_utils import yield_control


class _FakeQuery:
    def __init__(self, db: "_FakeDB", model):  # noqa: ANN001
        self._db = db
        self._model = model
        self._filters: dict[str, object] = {}

    def filter_by(self, **kwargs):  # noqa: ANN003, ANN202
        self._filters.update(kwargs)
        return self

    def first(self):  # noqa: ANN202
        for item in self._db.data.get(self._model, []):
            ok = True
            for key, value in self._filters.items():
                if getattr(item, key, None) != value:
                    ok = False
                    break
            if ok:
                return item
        return None


class _FakeDB:
    def __init__(self) -> None:
        self.data: dict[object, list[object]] = {Tenant: [], TenantMember: []}
        self.added: list[object] = []

    def query(self, model):  # noqa: ANN001, ANN202
        return _FakeQuery(self, model)

    def add(self, item: object) -> None:
        self.data.setdefault(type(item), []).append(item)
        self.added.append(item)


def test_ensure_tenant_member_for_jwt_user_creates_member_and_audits(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import tenant_member_provisioning_service as svc

    db = _FakeDB()
    tenant_id = uuid.UUID("00000000-0000-0000-0000-000000000000")
    db.data[Tenant].append(Tenant(id=tenant_id, name="t0", status="active", plan="basic"))

    called = {"audit": 0}
    monkeypatch.setattr(svc, "audit_log_event", lambda *_a, **_k: called.__setitem__("audit", called["audit"] + 1), raising=True)

    created = ensure_tenant_member_for_jwt_user(
        db,  # type: ignore[arg-type]
        tenant_id=tenant_id,
        user_id="alice",
        request_id="rid",
        ip="127.0.0.1",
        user_agent="pytest",
    )
    assert created is True
    assert any(isinstance(it, TenantMember) for it in db.added)
    assert called["audit"] == 1


def test_auth_dependency_calls_auto_provision_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services.tenant_member_provisioning_service as svc

    monkeypatch.setattr(settings, "AUTH_MODE", "jwt", raising=False)
    monkeypatch.setattr(settings, "ALGORITHM", "HS256", raising=False)
    monkeypatch.setattr(settings, "JWT_ISSUER", "", raising=False)
    monkeypatch.setattr(settings, "JWT_AUDIENCE", "", raising=False)
    monkeypatch.setattr(settings, "JWT_ENFORCE_TENANT_HEADER_MATCH", False, raising=False)
    monkeypatch.setattr(settings, "JWT_TENANT_CLAIM", "tenant_id", raising=False)
    monkeypatch.setattr(settings, "JWT_TENANT_MEMBER_AUTO_PROVISION_ENABLED", True, raising=False)

    secret_key = "k" * 40
    monkeypatch.setattr(settings, "SECRET_KEY", secret_key, raising=False)
    monkeypatch.setattr(settings, "SECRET_KEY_FALLBACKS", "", raising=False)

    tenant_id = "00000000-0000-0000-0000-000000000000"
    token = jwt.encode(
        {"sub": "jwt-user", "tenant_id": tenant_id, "exp": datetime.now(UTC) + timedelta(minutes=5)},
        secret_key,
        algorithm="HS256",
    )

    called = {"count": 0, "tenant_id": None, "user_id": None}

    def _fake_provision(**kwargs):  # noqa: ANN001, ANN202
        called["count"] += 1
        called["tenant_id"] = str(kwargs.get("tenant_id") or "")
        called["user_id"] = str(kwargs.get("user_id") or "")
        return True

    monkeypatch.setattr(svc, "maybe_auto_provision_jwt_tenant_member_best_effort", _fake_provision, raising=True)

    app = FastAPI()

    @app.get("/state")
    async def state_endpoint(*, request: Request, account_id: Annotated[str, Depends(get_current_account_id)]):  # noqa: B008
        await yield_control()
        return {
            "account_id": account_id,
            "state_user_id": getattr(request.state, "user_id", None),
            "state_tenant_id": str(getattr(request.state, "tenant_id", "")) if getattr(request.state, "tenant_id", None) else None,
        }

    client = TestClient(app)
    res = client.get("/state", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200, res.text
    assert called["count"] == 1
    assert called["tenant_id"] == tenant_id
    assert called["user_id"] == "jwt-user"
