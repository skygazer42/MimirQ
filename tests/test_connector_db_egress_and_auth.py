import asyncio
import datetime as _datetime
import sys
import uuid
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette import status as _starlette_status

if not hasattr(_datetime, "UTC"):
    _datetime.UTC = _datetime.timezone.utc  # type: ignore[attr-defined]
if not hasattr(_starlette_status, "HTTP_413_CONTENT_TOO_LARGE"):
    _starlette_status.HTTP_413_CONTENT_TOO_LARGE = 413  # type: ignore[attr-defined]
if not hasattr(_starlette_status, "HTTP_422_UNPROCESSABLE_CONTENT"):
    _starlette_status.HTTP_422_UNPROCESSABLE_CONTENT = 422  # type: ignore[attr-defined]

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db


class _DummyDB:
    def query(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("db.query should not be reached in this test")


def _override_get_db():  # noqa: ANN202
    yield _DummyDB()


class _QueryStub:
    def __init__(self, value):
        self._value = value

    def filter(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
        return self

    def first(self):  # noqa: ANN201
        return self._value


class _ConfigDB(_DummyDB):
    def __init__(self, value):
        self._value = value

    def query(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
        return _QueryStub(self._value)


def _build_validation_client(*, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    import app.api.v1.connectors_validation as validation_api

    tenant_id = uuid.uuid4()

    def _override_get_tenant_id() -> uuid.UUID:
        return tenant_id

    def _override_get_current_account_id() -> str:
        return "member-user"

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.include_router(validation_api.router, prefix="/api/v1/connectors")
    return TestClient(app)


def _build_runs_client(*, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    import app.api.v1.connectors  # noqa: F401
    import app.api.v1.connectors_runs as runs_api

    tenant_id = uuid.uuid4()

    def _override_get_tenant_id() -> uuid.UUID:
        return tenant_id

    def _override_get_current_account_id() -> str:
        return "member-user"

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.include_router(runs_api.router, prefix="/api/v1/connectors")
    return TestClient(app)


def _build_configs_client(*, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    import app.api.v1.connectors  # noqa: F401
    import app.api.v1.connectors_configs as configs_api

    tenant_id = uuid.uuid4()

    def _override_get_tenant_id() -> uuid.UUID:
        return tenant_id

    def _override_get_current_account_id() -> str:
        return "member-user"

    cfg = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        dataset_id=uuid.uuid4(),
        connector_id="mysql_catalog",
        config=_db_payload("db.example.com")["config"],
    )

    def _override_config_db():  # noqa: ANN202
        yield _ConfigDB(cfg)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_config_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.include_router(configs_api.router, prefix="/api/v1/connectors")
    return TestClient(app)


def _db_payload(host: str) -> dict[str, object]:
    return {
        "connector_id": "mysql_catalog",
        "config": {
            "host": host,
            "port": 3306,
            "database": "analytics",
            "username": "reader",
            "password": "secret",
        },
    }


def test_db_validate_requires_admin_permission(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.connectors_validation as validation_api

    client = _build_validation_client(monkeypatch=monkeypatch)

    monkeypatch.setattr(
        validation_api.DatasetService,
        "ensure_member",
        lambda *_args, **_kwargs: SimpleNamespace(role="member"),
        raising=True,
    )

    response = client.post("/api/v1/connectors/validate", json=_db_payload("db.example.com"))

    assert response.status_code == 403, response.text


def test_db_validate_rejects_private_destinations_before_connectivity_check(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.connectors_validation as validation_api

    client = _build_validation_client(monkeypatch=monkeypatch)

    monkeypatch.setattr(
        validation_api.DatasetService,
        "ensure_member",
        lambda *_args, **_kwargs: SimpleNamespace(role="owner"),
        raising=True,
    )
    monkeypatch.setattr(
        validation_api,
        "ensure_tenant_permission",
        lambda *_args, **_kwargs: SimpleNamespace(role="owner"),
        raising=True,
    )

    async def _unexpected_db_check(**_kwargs):  # noqa: ANN003
        raise AssertionError("DB connectivity check should not run for blocked destinations")

    monkeypatch.setattr(
        validation_api,
        "_check_db_connectivity_best_effort",
        _unexpected_db_check,
        raising=True,
    )

    response = client.post(
        "/api/v1/connectors/validate",
        json={**_db_payload("127.0.0.1"), "check_connectivity": True},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["ok"] is False
    assert body["checks"]["egress"]["ok"] is False
    assert any("127.0.0.1" in err["msg"] for err in body["errors"])


def test_db_run_creation_requires_admin_permission(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.connectors  # noqa: F401
    import app.api.v1.connectors_runs as runs_api
    import app.services.rbac_service as rbac_service

    client = _build_runs_client(monkeypatch=monkeypatch)

    monkeypatch.setattr(
        runs_api,
        "_validate_connector_run_enabled",
        lambda *_args, **_kwargs: None,
        raising=True,
    )
    monkeypatch.setattr(
        rbac_service.DatasetService,
        "ensure_member",
        lambda *_args, **_kwargs: SimpleNamespace(role="member"),
        raising=True,
    )

    response = client.post(
        "/api/v1/connectors/runs",
        json={**_db_payload("db.example.com"), "dataset_id": str(uuid.uuid4())},
    )

    assert response.status_code == 403, response.text


def test_db_run_creation_reports_blocked_destination_as_client_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.connectors  # noqa: F401
    import app.api.v1.connectors_runs as runs_api

    client = _build_runs_client(monkeypatch=monkeypatch)
    monkeypatch.setattr(runs_api, "_validate_connector_run_enabled", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(runs_api, "ensure_tenant_permission", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        runs_api.connectors_module,
        "_resolve_writable_dataset",
        lambda *_args, **_kwargs: SimpleNamespace(id=uuid.uuid4()),
    )
    monkeypatch.setattr(
        runs_api,
        "_validate_and_encrypt_run_config",
        lambda *_args, **_kwargs: (SimpleNamespace(host="127.0.0.1"), {}),
    )

    response = client.post(
        "/api/v1/connectors/runs",
        json={**_db_payload("127.0.0.1"), "dataset_id": str(uuid.uuid4())},
    )

    assert response.status_code == 400
    assert "blocked loopback address" in response.json()["detail"]


def test_db_saved_config_run_requires_admin_permission(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.connectors  # noqa: F401
    import app.api.v1.connectors_configs as configs_api
    import app.services.rbac_service as rbac_service

    client = _build_configs_client(monkeypatch=monkeypatch)

    monkeypatch.setattr(
        configs_api.connectors_module.DatasetService,
        "ensure_member",
        lambda *_args, **_kwargs: SimpleNamespace(role="member"),
        raising=True,
    )
    monkeypatch.setattr(
        rbac_service.DatasetService,
        "ensure_member",
        lambda *_args, **_kwargs: SimpleNamespace(role="member"),
        raising=True,
    )

    response = client.post(f"/api/v1/connectors/configs/{uuid.uuid4()}/run")

    assert response.status_code == 403, response.text


def test_db_egress_policy_rejects_private_resolution_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services.connector_egress_policy as policy

    monkeypatch.setattr(
        policy.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (0, 0, 0, "", ("10.0.0.5", 3306)),
            (0, 0, 0, "", ("93.184.216.34", 3306)),
        ],
        raising=True,
    )

    with pytest.raises(ValueError, match="10.0.0.5"):
        policy.validate_db_connector_destination("db.internal")


def test_db_egress_policy_allows_private_cidr_when_explicitly_allowlisted(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services.connector_egress_policy as policy

    monkeypatch.setattr(
        policy.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [(0, 0, 0, "", ("10.0.0.5", 3306))],
        raising=True,
    )

    resolved = policy.validate_db_connector_destination(
        "db.internal",
        allow_cidrs="10.0.0.0/8",
    )

    assert resolved == ["10.0.0.5"]


def test_mysql_connection_revalidates_egress_before_network_call(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.connectors.db.catalog_connectors import MySQLCatalogConnector

    calls: list[tuple[str, object]] = []

    def _fake_connect(**kwargs):  # noqa: ANN003
        calls.append(("connect", kwargs.get("host")))
        raise AssertionError("pymysql.connect should not be called for blocked destinations")

    monkeypatch.setitem(sys.modules, "pymysql", SimpleNamespace(connect=_fake_connect))

    connector = MySQLCatalogConnector()
    result = asyncio.run(
        connector.test_connection(
            {
                "host": "127.0.0.1",
                "port": 3306,
                "database": "analytics",
                "username": "reader",
                "password": "secret",
            }
        )
    )

    assert result.ok is False
    assert "127.0.0.1" in str((result.details or {}).get("error") or "")
    assert calls == []
