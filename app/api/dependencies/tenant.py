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


async def get_tenant_id(request: Request, x_tenant_id: str | None = Header(default=None)) -> UUID:
    """
    Get tenant ID from request header, using default value if not provided.
    """
    if bool(getattr(settings, "TENANT_PREFER_JWT_TENANT", False)):
        # Fast path: auth dependency may have already resolved a verified JWT tenant claim.
        state_tenant_id = getattr(request.state, "tenant_id", None)
        if state_tenant_id is not None:
            try:
                return state_tenant_id if isinstance(state_tenant_id, UUID) else UUID(str(state_tenant_id))
            except ValueError:
                # Ignore invalid cached value and fall back to header/default parsing.
                pass

        auth_mode = (getattr(settings, "AUTH_MODE", "jwt") or "jwt").lower()
        claim = str(getattr(settings, "JWT_TENANT_CLAIM", "") or "").strip()
        authorization = (request.headers.get("authorization") or "").strip()
        if auth_mode == "jwt" and claim and authorization:
            token = authorization
            if token.lower().startswith("bearer "):
                token = token[7:].strip()
            else:
                raise HTTPException(status_code=401, detail="Invalid Authorization header")

            try:
                payload = await decode_access_token(token)
            except ExpiredSignatureError as exc:
                raise HTTPException(status_code=401, detail="Token expired") from exc
            except JWTError as exc:
                raise HTTPException(status_code=401, detail="Invalid token") from exc

            # Cache verified payload for other dependencies in this request (best-effort).
            request.state._jwt_payload = payload  # noqa: SLF001

            raw_claim = payload.get(claim)
            if raw_claim is not None:
                try:
                    tenant_uuid = UUID(str(raw_claim))
                except ValueError as exc:
                    # If a tenant claim is configured but invalid, treat as invalid token.
                    raise HTTPException(status_code=401, detail="Invalid token") from exc
                request.state.tenant_id = tenant_uuid
                raw_sub = payload.get("sub")
                if raw_sub:
                    request.state.user_id = str(raw_sub)
                return tenant_uuid

    raw = (x_tenant_id or "").strip() or None
    tenant_header = str(getattr(settings, "TENANT_HEADER", "") or "X-Tenant-ID").strip() or "X-Tenant-ID"
    if not raw and tenant_header.lower() != "x-tenant-id":
        raw = (request.headers.get(tenant_header) or "").strip() or None
    if not raw:
        if is_production_env():
            raise HTTPException(status_code=400, detail=f"{tenant_header} header required")
        raw = settings.DEFAULT_TENANT_ID
    try:
        return UUID(str(raw))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid tenant id") from exc
