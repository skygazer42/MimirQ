from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException


def test_dify_type_aliases_share_the_types_package_objects() -> None:
    from app.api.v1 import integrations_dify
    from app.api.v1.dify_support import external_api
    from app.types import dify_integration

    for name in (
        "DifyRetrievalSetting",
        "DifyExternalKnowledgeRequest",
        "DifyExternalKnowledgeRecord",
        "DifyExternalKnowledgeResponse",
        "DifyConversationTurnRequest",
        "DifyConversationTurnResponse",
    ):
        owner_type = getattr(dify_integration, name)
        assert getattr(external_api, name) is owner_type
        assert getattr(integrations_dify, name) is owner_type

    assert external_api._DifyActor is dify_integration.DifyActor
    assert integrations_dify._DifyActor is dify_integration.DifyActor
    assert external_api._DifyKGFlags is dify_integration.DifyKGFlags
    assert integrations_dify._DifyKGFlags is dify_integration.DifyKGFlags


def test_authenticate_actor_preserves_configured_tenant_and_system_account(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.dify_integration import auth
    from app.types.dify_integration import DifyActor

    tenant_id = uuid4()
    monkeypatch.setattr(auth.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(auth.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", "expected-token", raising=False)
    monkeypatch.setattr(auth.settings, "DIFY_EXTERNAL_KNOWLEDGE_TENANT_ID", str(tenant_id), raising=False)
    monkeypatch.setattr(auth.settings, "DIFY_EXTERNAL_KNOWLEDGE_ACCOUNT_ID", "", raising=False)

    actor = auth.authenticate_actor(authorization="Bearer expected-token", tenant_header=None)

    assert actor == DifyActor(tenant_id=tenant_id, account_id="system:dify")


def test_authenticate_actor_rejects_missing_production_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.dify_integration import auth

    monkeypatch.setattr(auth.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(auth.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", "expected-token", raising=False)
    monkeypatch.setattr(auth.settings, "DIFY_EXTERNAL_KNOWLEDGE_TENANT_ID", "", raising=False)
    monkeypatch.setattr(auth, "is_production_env", lambda: True, raising=True)

    with pytest.raises(HTTPException) as exc_info:
        auth.authenticate_actor(authorization="Bearer expected-token", tenant_header=str(uuid4()))

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "Dify external knowledge tenant is not configured"


def test_authenticate_actor_uses_nonproduction_header_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.dify_integration import auth

    tenant_id = uuid4()
    monkeypatch.setattr(auth.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(auth.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", "expected-token", raising=False)
    monkeypatch.setattr(auth.settings, "DIFY_EXTERNAL_KNOWLEDGE_TENANT_ID", "", raising=False)
    monkeypatch.setattr(auth, "is_production_env", lambda: False, raising=True)

    actor = auth.authenticate_actor(authorization="Bearer expected-token", tenant_header=str(tenant_id))

    assert actor.tenant_id == UUID(str(tenant_id))


def test_authenticate_actor_rejects_wrong_bearer_token(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.dify_integration import auth

    monkeypatch.setattr(auth.settings, "DIFY_EXTERNAL_KNOWLEDGE_ENABLED", True, raising=False)
    monkeypatch.setattr(auth.settings, "DIFY_EXTERNAL_KNOWLEDGE_API_KEYS", "expected-token", raising=False)

    with pytest.raises(HTTPException) as exc_info:
        auth.authenticate_actor(authorization="Bearer wrong-token", tenant_header=None)

    assert exc_info.value.status_code == 401
