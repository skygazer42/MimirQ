"""Authenticate request headers and bind the verified account and tenant."""

import asyncio
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request
from jwt import ExpiredSignatureError, InvalidTokenError
from pydantic import ValidationError

from app.api.schemas.auth import AuthHeaders, JwtIdentity
from app.core.config import settings
from app.core.jwt_verify import decode_access_token
from app.core.logging_config import get_request_context, set_request_tenant_id, set_request_user_id
from app.rag.core.logging import get_logger
from app.services.jwt_membership_sync import sync_jwt_memberships

logger = get_logger("api.auth")
# Public error detail, not a credential.
INVALID_TOKEN_DETAIL = "Invalid token"  # noqa: S105


async def get_current_account_id(
    request: Request,
    headers: Annotated[AuthHeaders, Depends()],
) -> str:
    """Resolve the HTTP account in the request's own context.
    Keep this async so identity contextvars propagate to synchronous routes.
    """
    tenant_value = headers.x_tenant_id
    if not tenant_value:
        tenant_value = request.headers.get(settings.TENANT_HEADER.strip())
        if tenant_value:
            tenant_value = tenant_value.strip()
    return await get_current_account_id_from_headers(
        authorization=headers.authorization,
        x_user_id=headers.x_user_id,
        x_tenant_id=tenant_value,
        request=request,
    )


async def get_current_account_id_from_headers(
    authorization,
    x_user_id,
    x_tenant_id,
    request,
):
    # 开发模式：直接用 Header
    if settings.AUTH_MODE == "header":
        user_id = x_user_id.strip() if x_user_id is not None else None
        if not user_id:
            raise HTTPException(status_code=401, detail="X-User-ID header required")
        request.state.user_id = user_id
        set_request_user_id(user_id)
        return user_id

    # JWT 模式
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header required")
    token = authorization.strip()
    if not token.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Invalid Authorization header")
    payload = await _resolve_jwt_payload(token=token[7:].strip(), request=request)
    try:
        identity = JwtIdentity.from_payload(payload, settings.JWT_TENANT_CLAIM.strip())
    except ValidationError as exc:
        logger.warning("Invalid JWT identity claims")
        raise HTTPException(status_code=401, detail=INVALID_TOKEN_DETAIL) from exc

    if settings.JWT_ENFORCE_TENANT_HEADER_MATCH:
        if not identity.tenant_id:
            raise HTTPException(status_code=401, detail=INVALID_TOKEN_DETAIL)
        if not x_tenant_id:
            raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
        try:
            header_tenant_id = UUID(x_tenant_id.strip())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Invalid X-Tenant-ID header") from exc
        if header_tenant_id != identity.tenant_id:
            raise HTTPException(status_code=401, detail=INVALID_TOKEN_DETAIL)

    # 写入请求上下文
    request.state.user_id = identity.user_id
    set_request_user_id(identity.user_id)

    if identity.tenant_id:
        request.state.tenant_id = identity.tenant_id
        set_request_tenant_id(str(identity.tenant_id))

    optional_db_work_enabled = settings.JWT_GROUPS_SYNC_ENABLED or settings.JWT_TENANT_MEMBER_AUTO_PROVISION_ENABLED
    if identity.tenant_id and optional_db_work_enabled:
        user_agent = request.headers.get("User-Agent")
        if user_agent is not None:
            user_agent = user_agent.strip()
        await asyncio.to_thread(
            sync_jwt_memberships,
            tenant_id=identity.tenant_id,
            user_id=identity.user_id,
            payload=payload,
            request_id=get_request_context()["request_id"],
            ip=request.client.host.strip() if request.client else None,
            user_agent=user_agent,
        )
    return identity.user_id


async def _resolve_jwt_payload(*, token, request):
    cached = getattr(request.state, "_jwt_payload", None)
    if cached is not None:
        return cached
    try:
        payload = await decode_access_token(token)
    except ExpiredSignatureError as exc:
        logger.warning("Expired token attempted for access")
        raise HTTPException(status_code=401, detail="Token expired") from exc
    except InvalidTokenError as exc:
        logger.warning("Invalid token")
        raise HTTPException(status_code=401, detail=INVALID_TOKEN_DETAIL) from exc
    request.state._jwt_payload = payload
    return payload
