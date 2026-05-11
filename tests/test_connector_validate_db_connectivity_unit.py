from __future__ import annotations

import asyncio
import sys
import threading
import time
import types
import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db
from tests.helpers.async_utils import yield_control


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


class _MySQLThreadAwareCursor:
    def __init__(self) -> None:
        self._last_query = ""

    def execute(self, query: str) -> None:
        self._last_query = query

    def fetchone(self):  # noqa: ANN201
        return (1,)

    def fetchall(self):  # noqa: ANN201
        if self._last_query == "SHOW GRANTS":
            return [("GRANT SELECT ON *.* TO 'svc'@'%'",)]
        return []

    def __enter__(self) -> "_MySQLThreadAwareCursor":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001, ANN201
        _ = (exc_type, exc, tb)
        return False


class _MySQLThreadAwareConnection:
    def cursor(self) -> _MySQLThreadAwareCursor:
        return _MySQLThreadAwareCursor()

    def close(self) -> None:
        return None


class _SQLServerThreadAwareCursor:
    def __init__(self) -> None:
        self._last_query = ""

    def execute(self, query: str) -> None:
        self._last_query = query

    def fetchone(self):  # noqa: ANN201
        return (1,)

    def fetchall(self):  # noqa: ANN201
        if "fn_my_permissions" in self._last_query:
            return [("SELECT",)]
        return []


class _SQLServerThreadAwareConnection:
    def cursor(self) -> _SQLServerThreadAwareCursor:
        return _SQLServerThreadAwareCursor()

    def close(self) -> None:
        return None


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
    import app.api.v1.connectors_validation as connectors_module

    monkeypatch.setattr(connectors_module.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)

    called: dict[str, object] = {"n": 0, "last_connector_id": None}

    async def _fake_db_check(*, connector_id: str, cfg):  # noqa: ANN001
        await yield_control()
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
    assert float((checks.get("db_connectivity") or {}).get("latency_ms") or 0.0) == pytest.approx(12.3)
    assert (checks.get("db_connectivity") or {}).get("read_only") is True
    assert int(called["n"] or 0) == 1
    assert called["last_connector_id"] == connector_id


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("connector_cls_name", "module_name", "module_factory", "expected_read_only"),
    [
        (
            "MySQLCatalogConnector",
            "pymysql",
            lambda connect_calls, sleep_seconds: types.SimpleNamespace(
                connect=lambda **kwargs: _sleeping_mysql_connect(connect_calls, sleep_seconds, **kwargs)
            ),
            True,
        ),
        (
            "SQLServerCatalogConnector",
            "pyodbc",
            lambda connect_calls, sleep_seconds: types.SimpleNamespace(
                drivers=lambda: ["ODBC Driver 18 for SQL Server"],
                connect=lambda conn_str, timeout=0: _sleeping_sqlserver_connect(
                    connect_calls,
                    sleep_seconds,
                    conn_str=conn_str,
                    timeout=timeout,
                ),
            ),
            True,
        ),
    ],
)
async def test_db_catalog_test_connection_offloads_sync_driver_calls(
    monkeypatch: pytest.MonkeyPatch,
    connector_cls_name: str,
    module_name: str,
    module_factory,
    expected_read_only: bool,
) -> None:
    import app.connectors.db.catalog_connectors as catalog_module

    sleep_seconds = 0.2
    connect_calls: list[int] = []
    event_loop_thread_id = threading.get_ident()

    monkeypatch.setitem(sys.modules, module_name, module_factory(connect_calls, sleep_seconds))

    connector_cls = getattr(catalog_module, connector_cls_name)
    task = asyncio.create_task(
        connector_cls().test_connection(
            {"host": "localhost", "port": 1, "database": "demo", "username": "svc", "password": "secret"}
        )
    )

    t0 = time.perf_counter()
    await asyncio.sleep(0.01)
    elapsed = time.perf_counter() - t0

    assert elapsed < (sleep_seconds * 0.6)
    assert task.done() is False

    result = await task
    assert result.ok is True
    assert connect_calls and connect_calls[0] != event_loop_thread_id
    assert result.details["latency_ms"] is not None
    assert result.details["read_only"] is expected_read_only


def _sleeping_mysql_connect(connect_calls: list[int], sleep_seconds: float, **kwargs) -> _MySQLThreadAwareConnection:
    _ = kwargs
    connect_calls.append(threading.get_ident())
    time.sleep(sleep_seconds)
    return _MySQLThreadAwareConnection()


def _sleeping_sqlserver_connect(
    connect_calls: list[int],
    sleep_seconds: float,
    *,
    conn_str: str,
    timeout: int,
) -> _SQLServerThreadAwareConnection:
    _ = (conn_str, timeout)
    connect_calls.append(threading.get_ident())
    time.sleep(sleep_seconds)
    return _SQLServerThreadAwareConnection()
