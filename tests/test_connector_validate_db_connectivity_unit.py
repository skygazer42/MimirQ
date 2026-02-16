from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db


class _DummyDB:
    def add(self, _obj) -> None:  # noqa: ANN001
        return None

    def commit(self) -> None:
        return None

    def refresh(self, _obj) -> None:  # noqa: ANN001
        return None


def _override_get_db():  # noqa: ANN202
    yield _DummyDB()


def _override_get_tenant_id() -> uuid.UUID:
    return uuid.uuid4()


def _override_get_current_account_id() -> str:
    return "test-account"


@pytest.mark.parametrize(
    ("connector_id", "config"),
    [
        (
            "mysql_catalog",
            {"host": "localhost", "port": 3306, "database": "demo", "username": "svc", "password": "secret"},
        ),
        (
            "sqlserver_catalog",
            {"host": "localhost", "port": 1433, "database": "demo", "username": "svc", "password": "secret"},
        ),
    ],
)
def test_connectors_validate_db_connectivity_is_exposed_under_checks_db_connectivity(
    monkeypatch: pytest.MonkeyPatch,
    connector_id: str,
    config: dict,
) -> None:
    import app.api.v1.connectors as connectors_module

    monkeypatch.setattr(connectors_module.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)

    called: dict[str, object] = {"n": 0, "last_connector_id": None}

    async def _fake_db_check(*, connector_id: str, cfg):  # noqa: ANN001
        called["n"] = int(called["n"] or 0) + 1
        called["last_connector_id"] = connector_id
        return {"ok": True, "latency_ms": 12.3, "read_only": True}, []

    # Avoid real outbound DB calls in unit tests.
    monkeypatch.setattr(connectors_module, "_check_db_connectivity_best_effort", _fake_db_check, raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.post("/api/v1/connectors/validate")(connectors_module.validate_connector_config)
    client = TestClient(app)

    res = client.post(
        "/api/v1/connectors/validate",
        json={
            "connector_id": connector_id,
            "config": config,
            "check_connectivity": True,
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body.get("ok") is True
    checks = body.get("checks") or {}
    assert (checks.get("db_connectivity") or {}).get("ok") is True
    assert float((checks.get("db_connectivity") or {}).get("latency_ms") or 0.0) == 12.3
    assert (checks.get("db_connectivity") or {}).get("read_only") is True
    assert int(called["n"] or 0) == 1
    assert called["last_connector_id"] == connector_id

