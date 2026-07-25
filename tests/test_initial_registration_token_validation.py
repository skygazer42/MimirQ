import pytest

from app.core.config import Settings


def _set_prod_bootstrap_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("AUTH_MODE", "jwt")
    monkeypatch.setenv("SECRET_KEY", "x" * 32)
    monkeypatch.setenv("ALLOWED_HOSTS", "mimirq.example.com")
    monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com")
    monkeypatch.setenv("JWT_TENANT_CLAIM", "tenant_id")
    monkeypatch.setenv("DB_CREATE_ALL_ON_STARTUP", "false")
    monkeypatch.setenv("MIMIRQ_DB_CREATE_ALL_ON_STARTUP", "false")
    monkeypatch.setenv("DB_RUNTIME_MIGRATIONS_ENABLED", "false")
    monkeypatch.setenv("MIMIRQ_DB_RUNTIME_MIGRATIONS_ENABLED", "false")


def test_initial_registration_token_optional_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_prod_bootstrap_env(monkeypatch)
    monkeypatch.delenv("INITIAL_REGISTRATION_TOKEN", raising=False)
    assert Settings().INITIAL_REGISTRATION_TOKEN == ""


def test_initial_registration_token_accepts_sha256_digest_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_prod_bootstrap_env(monkeypatch)
    monkeypatch.setenv(
        "INITIAL_REGISTRATION_TOKEN",
        "sha256:fc17cbe42905e3308ba7175fd672651094e30c926f2bdd426636f12dd19df41b",
    )

    assert Settings().INITIAL_REGISTRATION_TOKEN.startswith("sha256:")


def test_initial_registration_token_rejects_invalid_sha256_digest(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_prod_bootstrap_env(monkeypatch)
    monkeypatch.setenv("INITIAL_REGISTRATION_TOKEN", "sha256:not-a-real-digest")

    with pytest.raises(ValueError) as excinfo:
        Settings()

    assert "INITIAL_REGISTRATION_TOKEN sha256 digest" in str(excinfo.value)
