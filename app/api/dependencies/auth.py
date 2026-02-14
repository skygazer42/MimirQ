"""
Authentication dependency.

Parses user identity from request headers.
"""

import logging
from uuid import UUID

from fastapi import Header, HTTPException, Request
from jose import ExpiredSignatureError, JWTError

from app.core.config import settings
from app.core.jwt_verify import decode_access_token
from app.core.logging_config import set_request_tenant_id, set_request_user_id

logger = logging.getLogger(__name__)

def _coerce_uuid(raw: object) -> str | None:
    value = str(raw or "").strip()
    if not value:
        return None
    try:
        return str(UUID(value))
    except ValueError:
        return None


def _get_jwt_tenant_id(payload: dict) -> str | None:
    claim = str(getattr(settings, "JWT_TENANT_CLAIM", "") or "").strip()
    if not claim:
        return None
    raw = payload.get(claim)
    if raw is None:
        return None
    tenant_id = _coerce_uuid(raw)
    if not tenant_id:
        # If a tenant claim is configured but invalid, treat it as an invalid token.
        raise HTTPException(status_code=401, detail="Invalid token")
    return tenant_id


async def get_current_account_id_from_headers(
    *,
    authorization: str | None,
    x_user_id: str | None,
    x_tenant_id: str | None,
    request: Request | None = None,
) -> str:
    """
    Resolve current account id from request headers.

    - AUTH_MODE=jwt: require Authorization: Bearer <token> and validate JWT.
    - AUTH_MODE=header (local/dev default): require X-User-ID header (unsafe; forbidden in production).
    """
    mode = (getattr(settings, "AUTH_MODE", "jwt") or "jwt").lower()

    if mode == "header":
        if not x_user_id:
            raise HTTPException(status_code=401, detail="X-User-ID header required")
        user_id = str(x_user_id)
        if request is not None:
            request.state.user_id = user_id
        set_request_user_id(user_id)
        return user_id

    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header required")

    token = authorization.strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    else:
        raise HTTPException(status_code=401, detail="Invalid Authorization header")

    payload = None
    if request is not None:
        cached = getattr(request.state, "_jwt_payload", None)
        if isinstance(cached, dict) and cached:
            payload = cached

    if payload is None:
        try:
            payload = await decode_access_token(token)
        except ExpiredSignatureError as exc:
            logger.warning("Expired token attempted for access")
            raise HTTPException(status_code=401, detail="Token expired") from exc
        except JWTError as exc:
            logger.warning("Invalid token: %s", str(exc)[:100])
            raise HTTPException(status_code=401, detail="Invalid token") from exc
        if request is not None:
            request.state._jwt_payload = payload

    user_id = payload.get("sub")
    if not user_id:
        logger.warning("Token missing 'sub' claim")
        raise HTTPException(status_code=401, detail="Invalid token")

    jwt_tenant_id = _get_jwt_tenant_id(payload)

    if bool(getattr(settings, "JWT_ENFORCE_TENANT_HEADER_MATCH", False)):
        if not jwt_tenant_id:
            raise HTTPException(status_code=401, detail="Invalid token")

        header_tenant_id = _coerce_uuid(x_tenant_id)
        if not header_tenant_id:
            raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
        if header_tenant_id != jwt_tenant_id:
            raise HTTPException(status_code=401, detail="Invalid token")

    user_id = str(user_id)
    if request is not None:
        request.state.user_id = user_id
    set_request_user_id(user_id)
    if jwt_tenant_id:
        set_request_tenant_id(jwt_tenant_id)
        if request is not None:
            request.state.tenant_id = UUID(jwt_tenant_id)
    return user_id


async def get_current_account_id(
    request: Request,
    authorization: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    x_tenant_id: str | None = Header(default=None),
) -> str:
    """
    FastAPI dependency wrapper.

    Important: keep this async so it runs in the main request context (not a threadpool),
    allowing request-scoped contextvars (e.g. user_id) to propagate to sync endpoints.
    """
    tenant_value = x_tenant_id
    if not tenant_value:
        tenant_header = str(getattr(settings, "TENANT_HEADER", "") or "X-Tenant-ID").strip() or "X-Tenant-ID"
        if tenant_header.lower() != "x-tenant-id":
            tenant_value = (request.headers.get(tenant_header) or "").strip() or None
    return await get_current_account_id_from_headers(
        authorization=authorization,
        x_user_id=x_user_id,
        x_tenant_id=tenant_value,
        request=request,
    )
