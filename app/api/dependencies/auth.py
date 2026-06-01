"""
Authentication dependency.

Parses user identity from request headers.
"""

from uuid import UUID

from fastapi import Header, HTTPException, Request
from jose import ExpiredSignatureError, JWTError

from app.core.config import settings
from app.core.jwt_verify import decode_access_token
from app.core.logging_config import set_request_tenant_id, set_request_user_id
from app.rag.core.logging import get_logger

logger = get_logger("api.auth")
INVALID_TOKEN_DETAIL = "Invalid token"  # noqa: S105 - public error detail, not a credential.

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
        raise HTTPException(status_code=401, detail=INVALID_TOKEN_DETAIL)
    return tenant_id


def _best_effort_client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return (forwarded.split(",")[0] or "").strip() or None
    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip() or None
    client = request.client
    if client is None:
        return None
    return str(client.host).strip() or None


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
            raise HTTPException(status_code=401, detail=INVALID_TOKEN_DETAIL) from exc
        if request is not None:
            request.state._jwt_payload = payload

    user_id = payload.get("sub")
    if not user_id:
        logger.warning("Token missing 'sub' claim")
        raise HTTPException(status_code=401, detail=INVALID_TOKEN_DETAIL)

    jwt_tenant_id = _get_jwt_tenant_id(payload)

    if bool(getattr(settings, "JWT_ENFORCE_TENANT_HEADER_MATCH", False)):
        if not jwt_tenant_id:
            raise HTTPException(status_code=401, detail=INVALID_TOKEN_DETAIL)

        header_tenant_id = _coerce_uuid(x_tenant_id)
        if not header_tenant_id:
            raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
        if header_tenant_id != jwt_tenant_id:
            raise HTTPException(status_code=401, detail=INVALID_TOKEN_DETAIL)

    user_id = str(user_id)
    if request is not None:
        request.state.user_id = user_id
    set_request_user_id(user_id)
    if jwt_tenant_id:
        set_request_tenant_id(jwt_tenant_id)
        if request is not None:
            request.state.tenant_id = UUID(jwt_tenant_id)

        # Optional enterprise: best-effort group sync from verified JWT payload (opt-in).
        if bool(getattr(settings, "JWT_GROUPS_SYNC_ENABLED", False)):
            try:
                from app.services.jwt_group_sync_service import maybe_sync_jwt_groups  # noqa: WPS433

                maybe_sync_jwt_groups(
                    tenant_id=UUID(jwt_tenant_id),
                    account_id=user_id,
                    jwt_payload=payload,
                )
            except Exception as exc:  # noqa: BLE001
                # Never block auth due to sync failures.
                logger.debug("JWT group sync failed during auth; continuing without sync: %s", exc)

        # Optional enterprise: auto-provision tenant_members for JWT-authenticated users (opt-in).
        if bool(getattr(settings, "JWT_TENANT_MEMBER_AUTO_PROVISION_ENABLED", False)):
            try:
                from app.core.database import SessionLocal  # noqa: WPS433
                from app.services.tenant_member_provisioning_service import (  # noqa: WPS433
                    maybe_auto_provision_jwt_tenant_member_best_effort,
                )

                request_id = None
                ip = None
                user_agent = None
                if request is not None:
                    request_id = str(getattr(request.state, "request_id", "") or "").strip() or None
                    ip = _best_effort_client_ip(request)
                    user_agent = (request.headers.get("User-Agent") or "").strip() or None

                maybe_auto_provision_jwt_tenant_member_best_effort(
                    db_factory=SessionLocal,
                    tenant_id=UUID(jwt_tenant_id),
                    user_id=user_id,
                    request_id=request_id,
                    ip=ip,
                    user_agent=user_agent,
                )
            except Exception as exc:  # noqa: BLE001
                # Never block auth due to auto-provisioning failures.
                logger.debug("JWT tenant member auto-provisioning failed during auth; continuing: %s", exc)
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
