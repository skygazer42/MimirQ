from __future__ import annotations

import sys
import types

import pytest


def test_has_write_privileges_from_text_does_not_flag_read_only_mysql_grants() -> None:
    from app.connectors.db.catalog_connectors import _has_write_privileges_from_text

    assert _has_write_privileges_from_text("GRANT SELECT ON *.* TO 'svc'@'%'") is False
    assert _has_write_privileges_from_text("GRANT OPTION") is True
    assert _has_write_privileges_from_text("UPDATE") is True


@pytest.mark.asyncio
async def test_check_db_connectivity_uses_connector_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.connectors as connectors_module

    captured: dict[str, object] = {}

    class _FakeConnector:
        async def test_connection(self, config):  # noqa: ANN001, ANN201
            captured["config"] = config

            class _Result:
                ok = True
                message = "connected"
                details = {"latency_ms": 7.7, "read_only": True, "warnings": []}

            return _Result()

    monkeypatch.setattr(
        connectors_module.connector_class_registry,
        "get",
        lambda connector_id: _FakeConnector,  # noqa: ARG005
        raising=True,
    )

    cfg = {"host": "localhost", "database": "demo"}
    check, warnings = await connectors_module._check_db_connectivity_best_effort(
        connector_id="mysql_catalog",
        cfg=cfg,
    )
    assert captured["config"] == cfg
    assert check == {"ok": True, "latency_ms": 7.7, "read_only": True}
    assert warnings == []


@pytest.mark.asyncio
async def test_check_db_connectivity_returns_empty_when_not_registered(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.connectors as connectors_module
    from app.connectors.registry import ConnectorNotFoundError

    def _raise_not_found(connector_id: str):  # noqa: ANN001
        raise ConnectorNotFoundError(connector_id)

    monkeypatch.setattr(connectors_module.connector_class_registry, "get", _raise_not_found, raising=True)

    check, warnings = await connectors_module._check_db_connectivity_best_effort(
        connector_id="unknown_connector",
        cfg={"k": "v"},
    )
    assert check == {}
    assert warnings == []


class _MySQLCursor:
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

    def __enter__(self) -> "_MySQLCursor":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:  # noqa: ANN001, ANN201
        _ = (exc_type, exc, tb)
        return False


class _MySQLConnection:
    def cursor(self) -> _MySQLCursor:
        return _MySQLCursor()

    def close(self) -> None:
        return None


class _SQLServerCursor:
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


class _SQLServerConnection:
    def cursor(self) -> _SQLServerCursor:
        return _SQLServerCursor()

    def close(self) -> None:
        return None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("connector_cls_name", "module_name", "module_stub"),
    [
        (
            "MySQLCatalogConnector",
            "pymysql",
            types.SimpleNamespace(connect=lambda **kwargs: _MySQLConnection()),
        ),
        (
            "SQLServerCatalogConnector",
            "pyodbc",
            types.SimpleNamespace(
                drivers=lambda: ["ODBC Driver 18 for SQL Server"],
                connect=lambda conn_str, timeout=0: _SQLServerConnection(),
            ),
        ),
    ],
)
async def test_catalog_connectors_offload_sync_db_checks_to_thread(
    monkeypatch: pytest.MonkeyPatch,
    connector_cls_name: str,
    module_name: str,
    module_stub: object,
) -> None:
    import app.connectors.db.catalog_connectors as catalog_module

    calls: list[tuple[object, tuple[object, ...], dict[str, object]]] = []

    async def _fake_to_thread(func, *args, **kwargs):  # noqa: ANN001, ANN202
        calls.append((func, args, kwargs))
        return func(*args, **kwargs)

    monkeypatch.setattr(catalog_module.asyncio, "to_thread", _fake_to_thread, raising=True)
    monkeypatch.setitem(sys.modules, module_name, module_stub)

    connector_cls = getattr(catalog_module, connector_cls_name)
    result = await connector_cls().test_connection(
        {"host": "localhost", "port": 1, "database": "demo", "username": "svc", "password": "secret"}
    )

    assert result.ok is True
    assert len(calls) == 1
    func, args, kwargs = calls[0]
    assert kwargs == {}
    assert func.__name__ == "_test_connection_sync"
    assert args and isinstance(args[0], dict)
