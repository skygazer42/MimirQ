import pytest
from pydantic import ValidationError

from app.core import config as config_module
from app.core.config import Settings


@pytest.mark.parametrize(
    "field_name",
    [
        "INPUT_GUARD_MODE",
        "RETRIEVAL_FUSION_STRATEGY",
        "VECTOR_BACKEND",
        "GOVERNANCE_PII_MODE",
    ],
)
def test_controlled_settings_reject_unknown_values(field_name: str):
    with pytest.raises(ValidationError):
        Settings.model_validate(
            {
                "SECRET_KEY": "test-only-signing-key-not-for-production",
                field_name: "typo",
            }
        )


def test_scim_requires_a_bound_tenant() -> None:
    with pytest.raises(ValidationError, match="SCIM_TENANT_ID required"):
        Settings.model_validate(
            {
                "SECRET_KEY": "test-only-signing-key-not-for-production",
                "SCIM_ENABLED": True,
                "SCIM_BEARER_TOKEN": "test-only-scim-token",
            }
        )


def test_dify_enabled_requires_tenant_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENV", "production")
    monkeypatch.delenv("DIFY_EXTERNAL_KNOWLEDGE_TENANT_ID", raising=False)
    monkeypatch.delenv("MIMIRQ_DIFY_EXTERNAL_KNOWLEDGE_TENANT_ID", raising=False)
    with pytest.raises(ValidationError, match="DIFY_EXTERNAL_KNOWLEDGE_TENANT_ID is required"):
        Settings.model_validate(
            {
                "AUTH_MODE": "jwt",
                "SECRET_KEY": "x" * 32,
                "ALLOWED_HOSTS": "api.example.com",
                "CORS_ORIGINS": "https://app.example.com",
                "JWT_TENANT_CLAIM": "tid",
                "DB_CREATE_ALL_ON_STARTUP": False,
                "DB_RUNTIME_MIGRATIONS_ENABLED": False,
                "DIFY_EXTERNAL_KNOWLEDGE_ENABLED": True,
                "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS": "k",
            }
        )


def test_pytest_argv_disables_repo_env_file_loading(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delitem(config_module.sys.modules, "pytest", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("PYTEST_VERSION", raising=False)
    monkeypatch.setattr(config_module.sys, "argv", ["/tmp/pytest"])

    assert config_module._should_disable_repo_env_file() is True
