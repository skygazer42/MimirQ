
import pytest

from app.core.config import Settings


def _set_prod_auth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # Settings validation enforces jwt auth + strong SECRET_KEY in production.
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("AUTH_MODE", "jwt")
    monkeypatch.setenv("SECRET_KEY", "x" * 32)


def test_allowed_hosts_required_in_production(monkeypatch: pytest.MonkeyPatch):
    _set_prod_auth_env(monkeypatch)
    monkeypatch.setenv("ALLOWED_HOSTS", "")

    with pytest.raises(ValueError) as excinfo:
        Settings()

    assert "ALLOWED_HOSTS" in str(excinfo.value)

