import pytest
from fastapi import HTTPException

import app.services.saml_bridge_service as saml_bridge_service


def test_memory_bridge_sessions_are_one_time(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(saml_bridge_service.settings, "SAML_REPLAY_REDIS_ENABLED", False)
    saml_bridge_service._memory_bridges.clear()

    session = saml_bridge_service.SamlBridgeSession(
        access_token="jwt-token",
        expires_in=3600,
        token_type="bearer",
        user={"id": "user-1"},
        return_to="/datasets/123",
    )

    code = saml_bridge_service.issue_saml_bridge_session(session)
    assert code

    restored = saml_bridge_service.consume_saml_bridge_session(code)
    assert restored.access_token == "jwt-token"
    assert restored.return_to == "/datasets/123"

    with pytest.raises(HTTPException, match="Invalid SAML bridge session"):
        saml_bridge_service.consume_saml_bridge_session(code)
