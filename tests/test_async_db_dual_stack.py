from __future__ import annotations

import importlib

import pytest


@pytest.mark.parametrize(
    ("sync_url", "expected_async_url"),
    [
        ("postgresql://user:pass@localhost:5432/mimirq", "postgresql+asyncpg://user:pass@localhost:5432/mimirq"),
        ("postgres://user:pass@localhost:5432/mimirq", "postgresql+asyncpg://user:pass@localhost:5432/mimirq"),
        ("sqlite:///./mimirq.db", "sqlite+aiosqlite:///./mimirq.db"),
        ("sqlite:///:memory:", "sqlite+aiosqlite:///:memory:"),
        ("postgresql+asyncpg://user:pass@localhost:5432/mimirq", "postgresql+asyncpg://user:pass@localhost:5432/mimirq"),
    ],
)
def test_to_async_database_url_converts_sync_drivers(sync_url: str, expected_async_url: str) -> None:
    from app.core.database_singleton import to_async_database_url

    assert to_async_database_url(sync_url) == expected_async_url


def test_async_session_factory_uses_async_driver_without_breaking_sync_exports(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.core.database as db_module
    import app.core.database_singleton as singleton_mod

    captured: dict[str, object] = {}

    class _FakeAsyncSession:
        pass

    def _fake_create_async_engine(url: str, **kwargs):  # noqa: ANN001, ANN003
        captured["url"] = url
        captured["kwargs"] = kwargs
        return object()

    def _fake_async_sessionmaker(**kwargs):  # noqa: ANN003
        captured["sessionmaker_kwargs"] = kwargs
        return _FakeAsyncSession

    monkeypatch.setattr(singleton_mod.settings, "DATABASE_URL", "postgresql://u:p@localhost:5432/mimirq", raising=False)
    monkeypatch.setattr(singleton_mod, "create_async_engine", _fake_create_async_engine, raising=True)
    monkeypatch.setattr(singleton_mod, "async_sessionmaker", _fake_async_sessionmaker, raising=True)
    monkeypatch.setattr(singleton_mod, "_async_engine", None, raising=True)
    monkeypatch.setattr(singleton_mod, "AsyncSessionLocal", None, raising=True)

    factory = singleton_mod.get_async_session_factory()

    assert factory is _FakeAsyncSession
    assert captured["url"] == "postgresql+asyncpg://u:p@localhost:5432/mimirq"
    assert "bind" in captured["sessionmaker_kwargs"]
    assert captured["sessionmaker_kwargs"]["autoflush"] is False
    assert captured["sessionmaker_kwargs"]["autocommit"] is False

    # Existing sync exports should remain importable/stable.
    reloaded_db_module = importlib.reload(db_module)
    assert hasattr(reloaded_db_module, "engine")
    assert hasattr(reloaded_db_module, "SessionLocal")
    assert hasattr(reloaded_db_module, "get_db")
