from types import SimpleNamespace
from uuid import uuid4

import pytest


@pytest.mark.parametrize("enabled", [False, True])
def test_settings_keeps_only_url_import_availability(monkeypatch: pytest.MonkeyPatch, enabled: bool) -> None:
    from app.api.v1 import settings as settings_api

    monkeypatch.setattr(settings_api, "_ensure_settings_readable", lambda *_args: None)
    monkeypatch.setattr(settings_api.settings, "URL_INGEST_ENABLED", enabled)

    response = settings_api.get_settings(tenant_id=uuid4(), account_id="reader", db=SimpleNamespace())

    assert response.model_dump()["url_ingest"] == {"enabled": enabled}


def test_settings_updates_cannot_change_url_fetch_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.v1 import settings as settings_api

    monkeypatch.setattr(settings_api.settings, "URL_INGEST_ENABLED", False)
    monkeypatch.setattr(settings_api.settings, "URL_INGEST_ALLOW_PRIVATE_IPS", False)
    monkeypatch.setattr(settings_api.settings, "GOVERNANCE_ENABLED", False)
    monkeypatch.setattr(settings_api.settings, "GOVERNANCE_PII_ANONYMIZE", False)
    monkeypatch.setattr(settings_api.settings, "GOVERNANCE_SECRETS_REDACT", False)
    monkeypatch.setattr(settings_api.settings, "GOVERNANCE_QUARANTINE_ON_DROP", False)
    env_vars = {"URL_INGEST_ENABLED": "false", "URL_INGEST_ALLOW_PRIVATE_IPS": "false"}
    updated_keys: list[str] = []
    request = settings_api.UpdateSettingsRequest.model_validate(
        {
            "url_ingest": {"enabled": True, "allow_private_ips": True, "max_bytes": 1234},
            "governance": {"enabled": True},
        }
    )

    settings_api._apply_request_settings_updates(request, env_vars, updated_keys)
    settings_api._apply_runtime_settings(env_vars, updated_keys)

    assert env_vars["URL_INGEST_ENABLED"] == "false"
    assert env_vars["URL_INGEST_ALLOW_PRIVATE_IPS"] == "false"
    assert all(not key.startswith("URL_INGEST_") for key in updated_keys)
    assert settings_api.settings.URL_INGEST_ENABLED is False
    assert settings_api.settings.URL_INGEST_ALLOW_PRIVATE_IPS is False
    assert settings_api.settings.GOVERNANCE_ENABLED is True
