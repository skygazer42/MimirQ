import pytest

from app.core.config import Settings
from app.core.health_checks import check_redis
from app.services.deps_diagnostics_service import _probe_redis


def _set_valid_production_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("AUTH_MODE", "jwt")
    monkeypatch.setenv("SECRET_KEY", "x" * 32)
    monkeypatch.setenv("ALLOWED_HOSTS", "api.example.com")
    monkeypatch.setenv("CORS_ORIGINS", "https://app.example.com")
    monkeypatch.setenv("JWT_TENANT_CLAIM", "tenant_id")


def test_check_redis_reports_chat_retrieval_and_semantic_usage() -> None:
    settings = type(
        "SettingsStub",
        (),
        {
            "TASK_QUEUE_ENABLED": False,
            "EMBEDDING_CACHE_ENABLED": False,
            "CHAT_RESPONSE_CACHE_ENABLED": True,
            "SECRET_KEY": "x" * 32,
            "RETRIEVAL_CANDIDATE_CACHE_ENABLED": True,
            "SEMANTIC_CACHE_ENABLED": True,
        },
    )()

    redis_status, ok, should_reset = check_redis(settings, get_client=lambda: type("Client", (), {"ping": lambda self: True})())

    assert ok is True
    assert should_reset is False
    assert redis_status["enabled"] is True
    assert redis_status["retrieval_candidate_singleflight_enabled"] is True
    assert redis_status["usage"] == {
        "task_queue": False,
        "embedding_cache": False,
        "chat_response_cache": True,
        "retrieval_candidate_singleflight": True,
        "retrieval_candidate_cache": True,
        "semantic_cache": True,
    }


def test_probe_redis_reports_usage_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.deps_diagnostics_service.settings.SECRET_KEY", "x" * 32, raising=False)
    monkeypatch.setattr("app.services.deps_diagnostics_service.settings.CHAT_RESPONSE_CACHE_ENABLED", True, raising=False)
    monkeypatch.setattr(
        "app.services.deps_diagnostics_service.settings.RETRIEVAL_CANDIDATE_SINGLEFLIGHT_ENABLED",
        True,
        raising=False,
    )
    monkeypatch.setattr("app.services.deps_diagnostics_service.settings.RETRIEVAL_CANDIDATE_CACHE_ENABLED", False, raising=False)
    monkeypatch.setattr("app.services.deps_diagnostics_service.settings.SEMANTIC_CACHE_ENABLED", True, raising=False)
    monkeypatch.setattr("app.services.deps_diagnostics_service.settings.EMBEDDING_CACHE_ENABLED", False, raising=False)
    monkeypatch.setattr("app.services.deps_diagnostics_service.settings.TASK_QUEUE_ENABLED", False, raising=False)

    class _Redis:
        @staticmethod
        def from_url(*_args, **_kwargs):  # noqa: ANN003
            return type(
                "Client",
                (),
                {
                    "ping": lambda self: True,
                    "info": lambda self, _section: {"redis_version": "7.2.0"},
                },
            )()

    monkeypatch.setattr("redis.Redis", _Redis, raising=False)

    status = _probe_redis()

    assert status["status"] == "connected"
    assert status["usage"] == {
        "task_queue": False,
        "embedding_cache": False,
        "chat_response_cache": True,
        "retrieval_candidate_singleflight": True,
        "retrieval_candidate_cache": False,
        "semantic_cache": True,
    }


def test_retrieval_candidate_cache_defaults_safe() -> None:
    configured = Settings()

    assert configured.RETRIEVAL_CANDIDATE_SINGLEFLIGHT_ENABLED is True
    assert configured.RETRIEVAL_CANDIDATE_SINGLEFLIGHT_WAIT_TIMEOUT_SEC == 60.0
    assert configured.RETRIEVAL_CANDIDATE_CACHE_ENABLED is False


def test_retrieval_candidate_singleflight_rejects_non_positive_wait_timeout() -> None:
    with pytest.raises(ValueError, match="RETRIEVAL_CANDIDATE_SINGLEFLIGHT_WAIT_TIMEOUT_SEC must be > 0"):
        Settings(RETRIEVAL_CANDIDATE_SINGLEFLIGHT_WAIT_TIMEOUT_SEC=0)


def test_check_redis_respects_singleflight_config_off() -> None:
    settings = type(
        "SettingsStub",
        (),
        {
            "TASK_QUEUE_ENABLED": False,
            "EMBEDDING_CACHE_ENABLED": False,
            "CHAT_RESPONSE_CACHE_ENABLED": False,
            "RETRIEVAL_CANDIDATE_SINGLEFLIGHT_ENABLED": False,
            "RETRIEVAL_CANDIDATE_CACHE_ENABLED": False,
            "SEMANTIC_CACHE_ENABLED": False,
        },
    )()

    redis_status, ok, should_reset = check_redis(settings)

    assert ok is True
    assert should_reset is False
    assert redis_status["enabled"] is False
    assert redis_status["usage"]["retrieval_candidate_singleflight"] is False


def test_check_redis_does_not_report_distributed_singleflight_without_encryption_key() -> None:
    settings = type(
        "SettingsStub",
        (),
        {
            "TASK_QUEUE_ENABLED": False,
            "EMBEDDING_CACHE_ENABLED": False,
            "CHAT_RESPONSE_CACHE_ENABLED": False,
            "SECRET_KEY": "",
            "RETRIEVAL_CANDIDATE_SINGLEFLIGHT_ENABLED": True,
            "RETRIEVAL_CANDIDATE_CACHE_ENABLED": False,
            "SEMANTIC_CACHE_ENABLED": False,
        },
    )()

    redis_status, ok, should_reset = check_redis(settings)

    assert ok is True
    assert should_reset is False
    assert redis_status["enabled"] is False
    assert redis_status["usage"]["retrieval_candidate_singleflight"] is False


def test_retrieval_distributed_admission_settings_default_disabled() -> None:
    configured = Settings()

    assert configured.RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_ENABLED is False
    assert configured.RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_MAX_CONCURRENCY == 0


def test_retrieval_distributed_admission_rejects_negative_concurrency() -> None:
    with pytest.raises(ValueError, match="RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_MAX_CONCURRENCY must be >= 0"):
        Settings(RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_MAX_CONCURRENCY=-1)


def test_production_requires_positive_retrieval_rebuild_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_valid_production_env(monkeypatch)

    with pytest.raises(ValueError, match="RETRIEVAL_REBUILD_MAX_CHUNKS must be > 0 in production"):
        Settings(RETRIEVAL_REBUILD_MAX_CHUNKS=0)


def test_non_production_allows_zero_retrieval_rebuild_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENV", "development")

    configured = Settings(RETRIEVAL_REBUILD_MAX_CHUNKS=0)

    assert configured.RETRIEVAL_REBUILD_MAX_CHUNKS == 0
