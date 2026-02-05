from __future__ import annotations

import contextlib
import uuid


class _FakeResult:
    def __init__(self, rows):  # noqa: ANN001
        self._rows = rows

    def mappings(self):  # noqa: ANN201
        return self

    def all(self):  # noqa: ANN201
        return list(self._rows)


class _FakeConn:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def execute(self, sql, params=None):  # noqa: ANN001
        s = str(sql)
        p = dict(params or {})
        self.calls.append((s, p))
        if "FROM sys.objects" in s:
            return _FakeResult(
                [
                    {"db_name": "demo", "schema_name": "dbo", "table_name": "users", "table_type": "table", "row_count_estimate": 123},
                ]
            )
        if "FROM sys.columns" in s:
            assert p.get("schema_name") == "dbo"
            assert p.get("table_name") == "users"
            return _FakeResult(
                [
                    {"ordinal": 1, "name": "id", "data_type": "int", "nullable": False, "comment": None},
                    {"ordinal": 2, "name": "name", "data_type": "nvarchar", "nullable": True, "comment": None},
                ]
            )
        raise AssertionError(f"unexpected sql: {s[:120]}")


def test_introspect_sqlserver_returns_tables_with_columns(monkeypatch):  # noqa: ANN001
    from app.connectors.db import catalog_runner

    fake_conn = _FakeConn()

    @contextlib.contextmanager
    def _fake_connect(_config):  # noqa: ANN001
        yield fake_conn

    monkeypatch.setattr(catalog_runner, "_connect_sqlserver", _fake_connect, raising=False)

    out = catalog_runner._introspect_sqlserver(  # type: ignore[attr-defined]
        tenant_id=uuid.uuid4(),
        dataset_id=uuid.uuid4(),
        config={"host": "x", "database": "demo", "username": "svc", "password": "secret", "include_schemas": ["dbo"]},
    )

    assert isinstance(out, list)
    assert len(out) == 1
    assert out[0]["schema_name"] == "dbo"
    assert out[0]["table_name"] == "users"
    assert out[0]["row_count_estimate"] == 123
    assert len(out[0].get("columns") or []) == 2
