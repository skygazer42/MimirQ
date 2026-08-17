import pytest
from pydantic import ValidationError

from app.core.config import Settings


def _production_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "AUTH_MODE": "jwt",
        "SECRET_KEY": "x" * 32,
        "ALLOWED_HOSTS": "api.example.com",
        "CORS_ORIGINS": "https://app.example.com",
        "JWT_TENANT_CLAIM": "tid",
        "DB_CREATE_ALL_ON_STARTUP": False,
        "DB_RUNTIME_MIGRATIONS_ENABLED": False,
    }
    payload.update(overrides)
    return payload


def test_dify_external_knowledge_keeps_api_key_validation_first() -> None:
    with pytest.raises(
        ValidationError,
        match="DIFY_EXTERNAL_KNOWLEDGE_API_KEYS required when DIFY_EXTERNAL_KNOWLEDGE_ENABLED=true",
    ):
        Settings.model_validate(
            {
                "SECRET_KEY": "test-only-signing-key-not-for-production",
                "DIFY_EXTERNAL_KNOWLEDGE_ENABLED": True,
                "DIFY_EXTERNAL_KNOWLEDGE_TOP_K_MAX": 0,
            }
        )


def test_chunk_retrieval_keeps_overlap_validation_before_llm_temperature() -> None:
    with pytest.raises(
        ValidationError,
        match=r"CHUNK_OVERLAP \(10\) must be less than CHUNK_SIZE \(10\)",
    ):
        Settings.model_validate(
            {
                "SECRET_KEY": "test-only-signing-key-not-for-production",
                "CHUNK_SIZE": 10,
                "CHUNK_OVERLAP": 10,
                "LLM_TEMPERATURE": 3,
            }
        )


def test_zero_valued_retrieval_setting_keeps_legacy_default_validation_semantics() -> None:
    settings = Settings.model_validate(
        {
            "SECRET_KEY": "test-only-signing-key-not-for-production",
            "RETRIEVAL_COMPACT_MIN_RECORDS": 0,
        }
    )

    assert settings.RETRIEVAL_COMPACT_MIN_RECORDS == 0


def test_jwt_production_trusted_tenant_source_message_is_exact(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENV", "production")

    with pytest.raises(ValidationError) as excinfo:
        Settings.model_validate(_production_payload(JWT_TENANT_CLAIM="", TENANT_HEADER_TRUSTED=False))

    assert excinfo.value.errors()[0]["msg"] == (
        "Value error, AUTH_MODE=jwt in production requires a trusted tenant source: "
        "set JWT_TENANT_CLAIM (recommended) or set TENANT_HEADER_TRUSTED=true "
        "to explicitly trust the client/gateway-supplied tenant header"
    )


def test_production_docs_enable_openapi_and_keep_write_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ENV", "production")

    settings = Settings.model_validate(_production_payload(API_DOCS_ENABLED=True))

    assert settings.API_DOCS_ENABLED is True
    assert settings.API_OPENAPI_ENABLED is True
    assert settings.SETTINGS_ENV_WRITE_ENABLED is False
