import uuid
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import get_current_account_id, get_tenant_id
from app.infrastructure.database.connection import get_db


class _DummyDB:
    def close(self) -> None:
        return None

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

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

    def close(self) -> None:
        return None


def _build_validation_client(*, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    import app.api.v1.connectors.validation as validation_api

    monkeypatch.setattr(validation_api, "SessionLocal", _DummyDB)

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
    import app.api.v1.connectors.runs as runs_api
    from app.services.runtime import retrieval_limiter

    monkeypatch.setattr(retrieval_limiter, "SessionLocal", _DummyDB)

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
    import app.api.v1.connectors.configs as configs_api
    from app.services.runtime import retrieval_limiter as rag_runtime_limiter

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
    monkeypatch.setattr(rag_runtime_limiter, "SessionLocal", lambda: _ConfigDB(cfg))

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
    import app.api.v1.connectors.validation as validation_api

    client = _build_validation_client(monkeypatch=monkeypatch)

    monkeypatch.setattr(
        validation_api.dataset_service,
        "ensure_member",
        lambda *_args, **_kwargs: SimpleNamespace(role="member"),
        raising=True,
    )

    response = client.post("/api/v1/connectors/validate", json=_db_payload("db.example.com"))

    assert response.status_code == 403, response.text


def test_db_validate_rejects_private_destinations_before_connectivity_check(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.connectors.validation as validation_api

    client = _build_validation_client(monkeypatch=monkeypatch)

    monkeypatch.setattr(
        validation_api.dataset_service,
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
        "check_database_connection",
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
    import app.services.connectors.runs as run_operations
    import app.services.identity.rbac as rbac_service

    client = _build_runs_client(monkeypatch=monkeypatch)

    monkeypatch.setattr(
        run_operations,
        "_validate_connector_run_enabled",
        lambda *_args, **_kwargs: None,
        raising=True,
    )
    monkeypatch.setattr(
        rbac_service.dataset_service,
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
    import app.services.connectors.runs as run_operations

    client = _build_runs_client(monkeypatch=monkeypatch)
    monkeypatch.setattr(run_operations, "_validate_connector_run_enabled", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(run_operations, "ensure_tenant_permission", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        run_operations.dataset_service,
        "resolve_writable_dataset",
        lambda *_args, **_kwargs: SimpleNamespace(id=uuid.uuid4()),
    )
    monkeypatch.setattr(
        run_operations,
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
    import app.services.connectors.configs as config_operations
    import app.services.identity.rbac as rbac_service

    client = _build_configs_client(monkeypatch=monkeypatch)

    monkeypatch.setattr(
        config_operations.dataset_service,
        "ensure_member",
        lambda *_args, **_kwargs: SimpleNamespace(role="member"),
        raising=True,
    )
    monkeypatch.setattr(
        rbac_service.dataset_service,
        "ensure_member",
        lambda *_args, **_kwargs: SimpleNamespace(role="member"),
        raising=True,
    )

    response = client.post(f"/api/v1/connectors/configs/{uuid.uuid4()}/run")

    assert response.status_code == 403, response.text


def test_db_egress_policy_rejects_private_resolution_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services.connectors.egress_policy as policy

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
    import app.services.connectors.egress_policy as policy

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
    from app.api.schemas.sources import MySQLCatalogConnectorConfig
    from app.connectors import connectivity

    calls = []

    def unexpected_connect(config):
        calls.append(config.host)
        raise AssertionError("blocked destination reached the database driver")

    monkeypatch.setattr(connectivity, "_check_mysql_connection", unexpected_connect)
    check, warnings = connectivity._check_database_connection(
        MySQLCatalogConnectorConfig(
            host="127.0.0.1", port=3306, database="analytics", username="reader", password="secret"
        )
    )
    assert check["ok"] is False
    assert "127.0.0.1" in check["error"]
    assert warnings[0]["code"] == "db_connectivity_failed"
    assert calls == []
