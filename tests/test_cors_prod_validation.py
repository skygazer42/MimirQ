from __future__ import annotations

import pytest

from app.core.config import Settings


def _set_prod_base_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("AUTH_MODE", "jwt")
    monkeypatch.setenv("SECRET_KEY", "x" * 32)
    monkeypatch.setenv("ALLOWED_HOSTS", "api.example.com")
    monkeypatch.setenv("MINIO_ENABLED", "false")


def test_prod_cors_rejects_empty_origins(monkeypatch: pytest.MonkeyPatch):
    _set_prod_base_env(monkeypatch)
    monkeypatch.setenv("CORS_ORIGINS", "")

    with pytest.raises(ValueError) as excinfo:
        Settings()

    assert "CORS_ORIGINS" in str(excinfo.value)


def test_prod_cors_rejects_localhost_origins(monkeypatch: pytest.MonkeyPatch):
    _set_prod_base_env(monkeypatch)
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:3000")

    with pytest.raises(ValueError) as excinfo:
        Settings()

    assert "CORS_ORIGINS" in str(excinfo.value)


def test_prod_cors_rejects_wildcard_origins(monkeypatch: pytest.MonkeyPatch):
    _set_prod_base_env(monkeypatch)
    monkeypatch.setenv("CORS_ORIGINS", "*")

    with pytest.raises(ValueError) as excinfo:
        Settings()

    assert "CORS_ORIGINS" in str(excinfo.value)

