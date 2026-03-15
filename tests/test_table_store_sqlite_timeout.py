from __future__ import annotations

from pathlib import Path

import pytest


class _DummyConn:
    def __init__(self) -> None:
        self.executed: list[str] = []
        self.row_factory = None

    def execute(self, sql: str):
        self.executed.append(str(sql))
        return self


def test_table_store_sqlite_timeout_is_clamped_and_applied(monkeypatch, tmp_path: Path) -> None:
    import app.services.table_store_service as svc

    calls: list[dict] = []
    last: dict[str, _DummyConn] = {}

    def fake_connect(*args, **kwargs):  # type: ignore[no-untyped-def]
        calls.append({"args": args, "kwargs": kwargs})
        conn = _DummyConn()
        last["conn"] = conn
        return conn

    monkeypatch.setattr(svc.sqlite3, "connect", fake_connect)
    monkeypatch.setattr(svc.settings, "TABLE_STORE_SQLITE_TIMEOUT_SEC", 9999.0, raising=False)

    svc._connect_rw(tmp_path / "x.db")

    assert calls, "expected sqlite3.connect to be called"
    assert calls[0]["kwargs"]["timeout"] == pytest.approx(120.0)
    assert any(s.strip().startswith("PRAGMA busy_timeout=120000") for s in last["conn"].executed)


def test_table_store_sqlite_timeout_allows_fail_fast_zero(monkeypatch, tmp_path: Path) -> None:
    import app.services.table_store_service as svc

    calls: list[dict] = []
    last: dict[str, _DummyConn] = {}

    def fake_connect(*args, **kwargs):  # type: ignore[no-untyped-def]
        calls.append({"args": args, "kwargs": kwargs})
        conn = _DummyConn()
        last["conn"] = conn
        return conn

    monkeypatch.setattr(svc.sqlite3, "connect", fake_connect)
    monkeypatch.setattr(svc.settings, "TABLE_STORE_SQLITE_TIMEOUT_SEC", -5.0, raising=False)

    svc._connect_ro(tmp_path / "x.db")

    assert calls[0]["kwargs"]["timeout"] == pytest.approx(0.0)
    assert calls[0]["kwargs"]["uri"] is True
    assert any(s.strip().startswith("PRAGMA busy_timeout=0") for s in last["conn"].executed)

