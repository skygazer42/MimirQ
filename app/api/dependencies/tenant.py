"""
Tenant identification dependency.

Parses tenant ID from request headers with default value fallback.
"""

from uuid import UUID

from fastapi import Header, HTTPException, Request
from jose import ExpiredSignatureError, JWTError

from app.core.config import settings
from app.core.env import is_production_env
from app.core.jwt_verify import decode_access_token


def _tenant_uuid_from_state(request: Request) -> UUID | None:
    state_tenant_id = getattr(request.state, "tenant_id", None)
    if state_tenant_id is None:
        return None
    try:
        return state_tenant_id if isinstance(state_tenant_id, UUID) else UUID(str(state_tenant_id))
    except ValueError:
        # Ignore invalid cached value and fall back to header/default parsing.
        return None


def _extract_bearer_token(authorization: str) -> str:
    token = authorization.strip()
    if not token.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Invalid Authorization header")
    return token[7:].strip()


async def _decode_tenant_jwt_payload(token: str) -> dict:
    try:
        return await decode_access_token(token)
    except ExpiredSignatureError as exc:
        raise HTTPException(status_code=401, detail="Token expired") from exc
    except JWTError as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc


def _tenant_uuid_from_claim(payload: dict, claim: str) -> UUID | None:
    raw_claim = payload.get(claim)
    if raw_claim is None:
        return None
    try:
        return UUID(str(raw_claim))
    except ValueError as exc:
        # If a tenant claim is configured but invalid, treat as invalid token.
        raise HTTPException(status_code=401, detail="Invalid token") from exc


def _cache_jwt_identity(request: Request, *, payload: dict, tenant_uuid: UUID) -> None:
    request.state._jwt_payload = payload  # noqa: SLF001
    request.state.tenant_id = tenant_uuid
    raw_sub = payload.get("sub")
    if raw_sub:
        request.state.user_id = str(raw_sub)


async def _preferred_jwt_tenant_id(request: Request) -> UUID | None:
    if tenant_uuid := _tenant_uuid_from_state(request):
        return tenant_uuid

    auth_mode = (getattr(settings, "AUTH_MODE", "jwt") or "jwt").lower()
    claim = str(getattr(settings, "JWT_TENANT_CLAIM", "") or "").strip()
    authorization = (request.headers.get("authorization") or "").strip()
    if auth_mode != "jwt" or not claim or not authorization:
        return None

    payload = await _decode_tenant_jwt_payload(_extract_bearer_token(authorization))
    tenant_uuid = _tenant_uuid_from_claim(payload, claim)
    if tenant_uuid is None:
        return None
    _cache_jwt_identity(request, payload=payload, tenant_uuid=tenant_uuid)
    return tenant_uuid


def _tenant_header_value(request: Request, x_tenant_id: str | None) -> tuple[str | None, str]:
    raw = (x_tenant_id or "").strip() or None
    tenant_header = str(getattr(settings, "TENANT_HEADER", "") or "X-Tenant-ID").strip() or "X-Tenant-ID"
    if not raw and tenant_header.lower() != "x-tenant-id":
        raw = (request.headers.get(tenant_header) or "").strip() or None
    return raw, tenant_header


def _tenant_uuid_from_header_or_default(request: Request, x_tenant_id: str | None) -> UUID:
    raw, tenant_header = _tenant_header_value(request, x_tenant_id)
    if not raw:
        if is_production_env():
            raise HTTPException(status_code=400, detail=f"{tenant_header} header required")
        raw = settings.DEFAULT_TENANT_ID
    try:
        return UUID(str(raw))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid tenant id") from exc


async def get_tenant_id(request: Request, x_tenant_id: str | None = Header(default=None)) -> UUID:
    """
    Get tenant ID from request header, using default value if not provided.
    """
    if tenant_uuid := await _preferred_jwt_tenant_id(request):
        return tenant_uuid
    return _tenant_uuid_from_header_or_default(request, x_tenant_id)
