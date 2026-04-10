from __future__ import annotations

import pytest

from app.core.config import Settings


def _set_prod_base_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("AUTH_MODE", "jwt")
    monkeypatch.setenv("SECRET_KEY", "x" * 32)
    monkeypatch.setenv("ALLOWED_HOSTS", "api.example.com")
    monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com")
    monkeypatch.setenv("MINIO_ENABLED", "false")


def test_cors_allow_credentials_defaults_false_in_production(monkeypatch: pytest.MonkeyPatch):
    _set_prod_base_env(monkeypatch)
    # Intentionally not setting CORS_ALLOW_CREDENTIALS.
    s = Settings()
    assert getattr(s, "CORS_ALLOW_CREDENTIALS", None) is False


def test_cors_allow_credentials_can_be_enabled_explicitly(monkeypatch: pytest.MonkeyPatch):
    _set_prod_base_env(monkeypatch)
    monkeypatch.setenv("CORS_ALLOW_CREDENTIALS", "true")
    s = Settings()
    assert getattr(s, "CORS_ALLOW_CREDENTIALS", None) is True

