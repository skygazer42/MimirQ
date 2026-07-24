import pytest

from app.core.config import Settings


def _set_valid_production_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("AUTH_MODE", "jwt")
    monkeypatch.setenv("SECRET_KEY", "x" * 32)
    monkeypatch.setenv("ALLOWED_HOSTS", "api.example.com")
    monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com")
    monkeypatch.setenv("JWT_TENANT_CLAIM", "tenant_id")
    monkeypatch.delenv("MIMIRQ_DB_CREATE_ALL_ON_STARTUP", raising=False)
    monkeypatch.delenv("DB_CREATE_ALL_ON_STARTUP", raising=False)
    monkeypatch.delenv("MIMIRQ_DB_RUNTIME_MIGRATIONS_ENABLED", raising=False)
    monkeypatch.delenv("DB_RUNTIME_MIGRATIONS_ENABLED", raising=False)
    monkeypatch.delenv("UVICORN_WORKERS", raising=False)


def test_production_disables_application_managed_schema_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_valid_production_env(monkeypatch)

    configured = Settings()

    assert configured.DB_CREATE_ALL_ON_STARTUP is False
    assert configured.DB_RUNTIME_MIGRATIONS_ENABLED is False


@pytest.mark.parametrize(
    "field_name",
    ["MIMIRQ_DB_CREATE_ALL_ON_STARTUP", "MIMIRQ_DB_RUNTIME_MIGRATIONS_ENABLED"],
)
def test_production_rejects_application_managed_schema(monkeypatch: pytest.MonkeyPatch, field_name: str) -> None:
    _set_valid_production_env(monkeypatch)
    monkeypatch.setenv(field_name, "true")

    with pytest.raises(ValueError, match="must be false in production"):
        Settings()


def test_production_multi_worker_rate_limit_requires_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_valid_production_env(monkeypatch)
    monkeypatch.setenv("UVICORN_WORKERS", "2")
    monkeypatch.setenv("RATE_LIMIT_REDIS_ENABLED", "false")

    with pytest.raises(ValueError, match="RATE_LIMIT_REDIS_ENABLED"):
        Settings()


def test_production_multi_worker_tenant_quota_requires_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_valid_production_env(monkeypatch)
    monkeypatch.setenv("UVICORN_WORKERS", "2")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    monkeypatch.setenv("TENANT_QPS_QUOTA_ENABLED", "true")
    monkeypatch.setenv("RATE_LIMIT_REDIS_ENABLED", "false")

    with pytest.raises(ValueError, match="TENANT_QPS_QUOTA_ENABLED"):
        Settings()


def test_production_multi_worker_bm25_requires_lazy_build(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_valid_production_env(monkeypatch)
    monkeypatch.setenv("UVICORN_WORKERS", "2")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "false")
    monkeypatch.setenv("BM25_INDEX_ENABLED", "true")
    monkeypatch.setenv("BM25_LAZY_BUILD_ENABLED", "false")

    with pytest.raises(ValueError, match="BM25_LAZY_BUILD_ENABLED"):
        Settings()


def test_production_multi_worker_accepts_distributed_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_valid_production_env(monkeypatch)
    monkeypatch.setenv("UVICORN_WORKERS", "2")
    monkeypatch.setenv("RATE_LIMIT_REDIS_ENABLED", "true")
    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/0")

    configured = Settings()

    assert configured.RATE_LIMIT_REDIS_ENABLED is True
