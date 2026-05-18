import pytest

from app.core.config import Settings


def test_tenant_resource_quota_settings_are_declared() -> None:
    settings = Settings(
        TENANT_DOC_QUOTA_ENABLED=True,
        TENANT_DOC_QUOTA_LIMIT=120,
        TENANT_STORAGE_QUOTA_ENABLED=True,
        TENANT_STORAGE_QUOTA_LIMIT_BYTES=10_000_000,
        TENANT_EMBED_CHAR_QUOTA_ENABLED=True,
        TENANT_EMBED_CHAR_QUOTA_LIMIT=500_000,
        TENANT_EMBED_CHAR_QUOTA_WINDOW_HOURS=12,
        TENANT_EMBED_CHAR_QUOTA_MODE="WARN",
    )

    assert settings.TENANT_DOC_QUOTA_ENABLED is True
    assert settings.TENANT_DOC_QUOTA_LIMIT == 120
    assert settings.TENANT_STORAGE_QUOTA_ENABLED is True
    assert settings.TENANT_STORAGE_QUOTA_LIMIT_BYTES == 10_000_000
    assert settings.TENANT_EMBED_CHAR_QUOTA_ENABLED is True
    assert settings.TENANT_EMBED_CHAR_QUOTA_LIMIT == 500_000
    assert settings.TENANT_EMBED_CHAR_QUOTA_WINDOW_HOURS == 12
    assert settings.TENANT_EMBED_CHAR_QUOTA_MODE == "warn"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("TENANT_DOC_QUOTA_LIMIT", -1, "TENANT_DOC_QUOTA_LIMIT must be >= 0"),
        ("TENANT_STORAGE_QUOTA_LIMIT_BYTES", -1, "TENANT_STORAGE_QUOTA_LIMIT_BYTES must be >= 0"),
        ("TENANT_EMBED_CHAR_QUOTA_LIMIT", -1, "TENANT_EMBED_CHAR_QUOTA_LIMIT must be >= 0"),
        ("TENANT_EMBED_CHAR_QUOTA_WINDOW_HOURS", 0, "TENANT_EMBED_CHAR_QUOTA_WINDOW_HOURS must be > 0"),
        ("TENANT_EMBED_CHAR_QUOTA_MODE", "drop", "TENANT_EMBED_CHAR_QUOTA_MODE must be one of: block, warn"),
    ],
)
def test_tenant_resource_quota_settings_validate_guardrails(field: str, value: object, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        Settings(**{field: value})
