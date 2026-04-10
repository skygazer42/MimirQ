from __future__ import annotations

import pytest


def _set_prod_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("AUTH_MODE", "jwt")
    monkeypatch.setenv("SECRET_KEY", "x" * 32)
    monkeypatch.setenv("ALLOWED_HOSTS", "api.example.com")
    monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com")
    monkeypatch.setenv("MINIO_ENABLED", "false")


def test_docs_and_openapi_disabled_by_default_in_production(monkeypatch: pytest.MonkeyPatch):
    _set_prod_env(monkeypatch)

    from app.core.config import Settings

    s = Settings()
    assert s.API_DOCS_ENABLED is False
    assert s.API_OPENAPI_ENABLED is False
