from __future__ import annotations

import importlib

import pytest


def _set_prod_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("AUTH_MODE", "jwt")
    monkeypatch.setenv("SECRET_KEY", "x" * 32)
    monkeypatch.setenv("ALLOWED_HOSTS", "api.example.com")
    monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com")


def test_docs_and_openapi_disabled_by_default_in_production(monkeypatch: pytest.MonkeyPatch):
    _set_prod_env(monkeypatch)

    import app.core.config as cfg
    import app.main as main_mod

    importlib.reload(cfg)
    importlib.reload(main_mod)

    assert main_mod.app.docs_url is None
    assert main_mod.app.redoc_url is None
    assert main_mod.app.openapi_url is None

