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


def test_dify_resolution_mode_rejects_unknown_values() -> None:
    with pytest.raises(ValidationError, match="DIFY_EXTERNAL_KNOWLEDGE_RESOLUTION_MODE must be one of"):
        Settings.model_validate(
            {
                "SECRET_KEY": "test-only-signing-key-not-for-production",
                "DIFY_EXTERNAL_KNOWLEDGE_RESOLUTION_MODE": "typo",
            }
        )


def test_dify_direct_dataset_uuid_mode_is_forbidden_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENV", "production")

    with pytest.raises(ValidationError, match="allow_dataset_uuid is not allowed in production"):
        Settings.model_validate(
            {
                "AUTH_MODE": "jwt",
                "SECRET_KEY": "x" * 32,
                "ALLOWED_HOSTS": "api.example.com",
                "CORS_ORIGINS": "https://app.example.com",
                "JWT_TENANT_CLAIM": "tid",
                "DB_CREATE_ALL_ON_STARTUP": False,
                "DB_RUNTIME_MIGRATIONS_ENABLED": False,
                "DIFY_EXTERNAL_KNOWLEDGE_RESOLUTION_MODE": "allow_dataset_uuid",
            }
        )


def test_runtime_warmup_required_for_ready_requires_warmup_enabled() -> None:
    with pytest.raises(ValidationError, match="RAG_RUNTIME_WARMUP_ENABLED must be true"):
        Settings.model_validate(
            {
                "SECRET_KEY": "test-only-signing-key-not-for-production",
                "RAG_RUNTIME_WARMUP_ENABLED": False,
                "RAG_RUNTIME_WARMUP_REQUIRED_FOR_READY": True,
            }
        )


def test_object_storage_rejects_unknown_provider() -> None:
    with pytest.raises(ValidationError, match="unsupported object storage provider"):
        Settings.model_validate(
            {
                "SECRET_KEY": "test-only-signing-key-not-for-production",
                "OBJECT_STORAGE_PROVIDER": "typo",
            }
        )


def test_object_storage_documents_require_enabled_store() -> None:
    with pytest.raises(ValidationError, match="documents_enabled requires OBJECT_STORAGE.enabled=true"):
        Settings.model_validate(
            {
                "SECRET_KEY": "test-only-signing-key-not-for-production",
                "OBJECT_STORAGE_DOCUMENTS_ENABLED": True,
            }
        )


@pytest.mark.parametrize("missing_field", ["endpoint", "access_key", "secret_key", "bucket_name"])
def test_enabled_object_storage_requires_complete_connection_settings(missing_field: str) -> None:
    payload = {
        "SECRET_KEY": "test-only-signing-key-not-for-production",
        "OBJECT_STORAGE_ENABLED": True,
        "OBJECT_STORAGE_ENDPOINT": "s3.example.test:443",
        "OBJECT_STORAGE_ACCESS_KEY": "access",
        "OBJECT_STORAGE_SECRET_KEY": "secret",
        "OBJECT_STORAGE_BUCKET_NAME": "documents",
    }
    payload[f"OBJECT_STORAGE_{missing_field.upper()}"] = ""

    with pytest.raises(ValidationError, match=rf"OBJECT_STORAGE\.{missing_field} is required"):
        Settings.model_validate(payload)


def test_object_storage_region_profiles_must_be_valid_json_objects() -> None:
    with pytest.raises(ValidationError, match="OBJECT_STORAGE_REGION_PROFILES must be a valid JSON object"):
        Settings.model_validate(
            {
                "SECRET_KEY": "test-only-signing-key-not-for-production",
                "OBJECT_STORAGE_REGION_PROFILES": "not-json",
            }
        )


def test_enabled_object_storage_region_profile_can_supply_connection_settings() -> None:
    configured = Settings.model_validate(
        {
            "SECRET_KEY": "test-only-signing-key-not-for-production",
            "DATA_REGION": " CN-Shanghai ",
            "OBJECT_STORAGE_REGION_PROFILES": (
                '{"cn-shanghai":{"provider":"aliyun_oss","enabled":true,'
                '"endpoint":"oss.example.test:443","access_key":"access",'
                '"secret_key":"secret","bucket_name":"documents","documents_enabled":true}}'
            ),
        }
    )

    assert configured.DATA_REGION == "cn-shanghai"


def test_regioned_document_object_storage_requires_matching_profile() -> None:
    with pytest.raises(ValidationError, match="DATA_REGION must have a matching"):
        Settings.model_validate(
            {
                "SECRET_KEY": "test-only-signing-key-not-for-production",
                "DATA_REGION": "cn-shanghai",
                "OBJECT_STORAGE_ENABLED": True,
                "OBJECT_STORAGE_DOCUMENTS_ENABLED": True,
                "OBJECT_STORAGE_ENDPOINT": "s3.example.test:443",
                "OBJECT_STORAGE_ACCESS_KEY": "access",
                "OBJECT_STORAGE_SECRET_KEY": "secret",
                "OBJECT_STORAGE_BUCKET_NAME": "documents",
            }
        )


def test_pytest_argv_disables_repo_env_file_loading(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delitem(config_module.sys.modules, "pytest", raising=False)
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.delenv("PYTEST_VERSION", raising=False)
    monkeypatch.setattr(config_module.sys, "argv", ["/tmp/pytest"])

    assert config_module._should_disable_repo_env_file() is True
