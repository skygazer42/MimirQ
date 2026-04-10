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


def test_settings_env_write_disabled_by_default_in_production(monkeypatch: pytest.MonkeyPatch):
    _set_prod_base_env(monkeypatch)
    s = Settings()
    assert getattr(s, "SETTINGS_ENV_WRITE_ENABLED", None) is False


def test_settings_env_write_can_be_enabled_explicitly(monkeypatch: pytest.MonkeyPatch):
    _set_prod_base_env(monkeypatch)
    monkeypatch.setenv("SETTINGS_ENV_WRITE_ENABLED", "true")
    s = Settings()
    assert getattr(s, "SETTINGS_ENV_WRITE_ENABLED", None) is True

