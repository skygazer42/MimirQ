from uuid import UUID

import pytest
from fastapi import HTTPException, Request

from app.api import dependencies as auth

TENANT = UUID("12345678-1234-5678-1234-567812345678")


def _verified_request(monkeypatch, payload):
    monkeypatch.setattr(auth.settings, "AUTH_MODE", "jwt")
    monkeypatch.setattr(auth.settings, "JWT_TENANT_CLAIM", "tenant")
    monkeypatch.setattr(auth.settings, "JWT_ENFORCE_TENANT_HEADER_MATCH", False)
    monkeypatch.setattr(auth.settings, "TENANT_HEADER", "X-Tenant-ID")
    decoded = []

    async def decode(token):
        decoded.append(token)
        return payload

    monkeypatch.setattr(auth, "decode_access_token", decode)
    return Request({"type": "http", "headers": [(b"authorization", b"Bearer verified-token")]}), decoded


@pytest.mark.asyncio
async def test_cached_request_identity_keeps_native_tenant_without_a_second_token_read(monkeypatch):
    request, decoded = _verified_request(monkeypatch, {"sub": "member", "tenant": str(TENANT)})
    tenant = await auth.get_tenant_id(request)
    assert isinstance(tenant, UUID) and tenant == TENANT
    assert await auth.get_current_account_id(request) == "member"
    assert await auth.get_tenant_id(request) is tenant
    assert request.state.jwt_payload == {"sub": "member", "tenant": str(TENANT)}
    assert request.state.tenant_id_source == "jwt"
    assert decoded == ["verified-token"]


@pytest.mark.asyncio
@pytest.mark.parametrize("raw", [12345678123456781234567812345678, [], {}])
async def test_jwt_tenant_claim_rejects_non_string_values_at_request_boundary(raw, monkeypatch):
    request, _decoded = _verified_request(monkeypatch, {"sub": "member", "tenant": raw})
    with pytest.raises(HTTPException) as error:
        await auth.get_tenant_id(request)
    assert error.value.status_code == 401


@pytest.mark.asyncio
async def test_required_tenant_claim_cannot_be_replaced_by_a_header_or_default(monkeypatch):
    request, _decoded = _verified_request(monkeypatch, {"sub": "member"})
    request.scope["headers"].append((b"x-tenant-id", str(TENANT).encode()))
    monkeypatch.setattr(auth.settings, "JWT_ENFORCE_TENANT_HEADER_MATCH", True)
    with pytest.raises(HTTPException) as error:
        await auth.get_tenant_id(request)
    assert error.value.status_code == 401


@pytest.mark.asyncio
async def test_verified_tenant_remains_native_in_request_and_logging_context(monkeypatch):
    request, _decoded = _verified_request(monkeypatch, {"sub": "member", "tenant": str(TENANT)})
    tenants, accounts = [], []
    monkeypatch.setattr(auth, "set_request_tenant_id", tenants.append)
    monkeypatch.setattr(auth, "set_request_user_id", accounts.append)
    tenant = await auth.get_tenant_id(request)
    assert request.state.tenant_id is tenant
    assert tenants == [str(TENANT)]
    assert accounts == ["member"]


@pytest.mark.asyncio
async def test_missing_credentials_cannot_produce_a_default_account_identity(monkeypatch):
    monkeypatch.setattr(auth.settings, "AUTH_MODE", "jwt")
    request = Request({"type": "http", "headers": []})
    with pytest.raises(HTTPException) as error:
        await auth.get_current_account_id(request)
    assert error.value.status_code == 401
    assert not hasattr(request.state, "authenticated_account_id")
