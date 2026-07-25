
import pytest

from app.core.config import Settings


def _set_valid_prod_jwt_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # Minimal production env that satisfies every other startup guard so the
    # tenant-source check is the only thing under test.
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("AUTH_MODE", "jwt")
    monkeypatch.setenv("SECRET_KEY", "x" * 32)
    monkeypatch.setenv("ALLOWED_HOSTS", "api.example.com")
    monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com")
    monkeypatch.setenv("DB_CREATE_ALL_ON_STARTUP", "false")
    monkeypatch.setenv("MIMIRQ_DB_CREATE_ALL_ON_STARTUP", "false")
    monkeypatch.setenv("DB_RUNTIME_MIGRATIONS_ENABLED", "false")
    monkeypatch.setenv("MIMIRQ_DB_RUNTIME_MIGRATIONS_ENABLED", "false")
    monkeypatch.delenv("JWT_TENANT_CLAIM", raising=False)
    monkeypatch.delenv("TENANT_HEADER_TRUSTED", raising=False)


def test_jwt_production_without_trusted_tenant_source_rejected(monkeypatch: pytest.MonkeyPatch):
    _set_valid_prod_jwt_env(monkeypatch)

    with pytest.raises(ValueError) as excinfo:
        Settings()

    message = str(excinfo.value)
    assert "JWT_TENANT_CLAIM" in message
    assert "TENANT_HEADER_TRUSTED" in message


def test_jwt_production_with_tenant_claim_accepted(monkeypatch: pytest.MonkeyPatch):
    _set_valid_prod_jwt_env(monkeypatch)
    monkeypatch.setenv("JWT_TENANT_CLAIM", "tid")

    assert Settings().JWT_TENANT_CLAIM == "tid"


def test_jwt_production_with_explicit_header_trust_accepted(monkeypatch: pytest.MonkeyPatch):
    _set_valid_prod_jwt_env(monkeypatch)
    monkeypatch.setenv("TENANT_HEADER_TRUSTED", "true")

    assert Settings().TENANT_HEADER_TRUSTED is True


def test_non_production_without_tenant_claim_still_boots(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("ENV", raising=False)
    monkeypatch.delenv("JWT_TENANT_CLAIM", raising=False)

    assert Settings(SECRET_KEY="x" * 32).JWT_TENANT_CLAIM == ""
