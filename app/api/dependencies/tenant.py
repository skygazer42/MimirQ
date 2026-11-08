"""Resolve tenant identity from verified JWT claims or explicit request headers."""

from typing import Any
from uuid import UUID

from fastapi import Header, HTTPException, Request
from jwt import ExpiredSignatureError, InvalidTokenError

from app.core.config import settings
from app.core.env import is_production_env
from app.core.jwt_verify import decode_access_token


def _extract_bearer_token(authorization: str) -> str:
    token = authorization.strip()
    if not token.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Invalid Authorization header")
    return token[7:].strip()


async def _decode_tenant_jwt_payload(token: str) -> dict[str, Any]:
    try:
        return await decode_access_token(token)
    except ExpiredSignatureError as exc:
        raise HTTPException(status_code=401, detail="Token expired") from exc
    except InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc


def _tenant_uuid_from_claim(payload: dict[str, Any], claim: str) -> UUID | None:
    raw_claim = payload.get(claim)
    if raw_claim is None:
        return None
    try:
        return UUID(str(raw_claim))
    except ValueError as exc:
        # If a tenant claim is configured but invalid, treat as invalid token.
        raise HTTPException(status_code=401, detail="Invalid token") from exc


def _cache_jwt_identity(request: Request, *, payload: dict[str, Any], tenant_uuid: UUID) -> None:
    request.state._jwt_payload = payload  # noqa: SLF001
    request.state.tenant_id = tenant_uuid
    request.state.tenant_id_source = "jwt"
    if request.client is not None:
        request.state.client_host = request.client.host.strip()
    raw_sub = payload.get("sub")
    if raw_sub:
        request.state.user_id = str(raw_sub)


async def _preferred_jwt_tenant_id(request: Request) -> UUID | None:
    tenant_uuid = getattr(request.state, "tenant_id", None)
    if tenant_uuid is not None:
        return tenant_uuid

    claim = settings.JWT_TENANT_CLAIM.strip()
    authorization = request.headers.get("authorization", "").strip()
    if settings.AUTH_MODE != "jwt" or not claim or not authorization:
        return None

    payload = await _decode_tenant_jwt_payload(_extract_bearer_token(authorization))
    tenant_uuid = _tenant_uuid_from_claim(payload, claim)
    if tenant_uuid is None:
        return None
    _cache_jwt_identity(request, payload=payload, tenant_uuid=tenant_uuid)
    return tenant_uuid


def _tenant_uuid_from_header_or_default(request: Request, x_tenant_id: str | None) -> UUID:
    tenant_header = settings.TENANT_HEADER.strip() or "X-Tenant-ID"
    raw = (x_tenant_id if x_tenant_id is not None else "").strip()
    if not raw and tenant_header.lower() != "x-tenant-id":
        raw = request.headers.get(tenant_header, "").strip()
    source = "header"
    if not raw:
        if is_production_env():
            raise HTTPException(status_code=400, detail=f"{tenant_header} header required")
        raw = settings.DEFAULT_TENANT_ID
        source = "default"
    try:
        tenant_uuid = UUID(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid tenant id") from exc
    request.state.tenant_id = tenant_uuid
    request.state.tenant_id_source = source
    if request.client is not None:
        request.state.client_host = request.client.host.strip()
    return tenant_uuid


async def get_tenant_id(request: Request, x_tenant_id: str | None = Header(default=None)) -> UUID:
    """Prefer a verified tenant; require headers in production and use the local default otherwise."""
    if tenant_uuid := await _preferred_jwt_tenant_id(request):
        return tenant_uuid
    return _tenant_uuid_from_header_or_default(request, x_tenant_id)


def get_tenant_id_from_header(request: Request, x_tenant_id: str | None = Header(default=None)) -> UUID:
    """Resolve tenant context without interpreting a route-specific bearer token as JWT."""
    return _tenant_uuid_from_header_or_default(request, x_tenant_id)
