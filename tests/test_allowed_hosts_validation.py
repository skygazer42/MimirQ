
import pytest

from app.core.config import Settings


def test_auth_mode_defaults_to_jwt(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("AUTH_MODE", raising=False)

    assert Settings(SECRET_KEY="x" * 32).AUTH_MODE == "jwt"


def _set_prod_auth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # Settings validation enforces jwt auth + strong SECRET_KEY in production.
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("AUTH_MODE", "jwt")
    monkeypatch.setenv("SECRET_KEY", "x" * 32)
    monkeypatch.setenv("DB_CREATE_ALL_ON_STARTUP", "false")
    monkeypatch.setenv("MIMIRQ_DB_CREATE_ALL_ON_STARTUP", "false")
    monkeypatch.setenv("DB_RUNTIME_MIGRATIONS_ENABLED", "false")
    monkeypatch.setenv("MIMIRQ_DB_RUNTIME_MIGRATIONS_ENABLED", "false")


def test_allowed_hosts_required_in_production(monkeypatch: pytest.MonkeyPatch):
    _set_prod_auth_env(monkeypatch)
    monkeypatch.setenv("ALLOWED_HOSTS", "")

    with pytest.raises(ValueError) as excinfo:
        Settings()

    assert "ALLOWED_HOSTS" in str(excinfo.value)
