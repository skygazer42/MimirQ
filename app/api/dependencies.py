"""Authenticate requests and bind their account and workspace context."""

from typing import Annotated, AsyncIterator
from uuid import UUID

from fastapi import Header, HTTPException, Request
from jwt import ExpiredSignatureError, InvalidTokenError
from pydantic import TypeAdapter, ValidationError

from app.api.schemas.identity import AuthHeaders
from app.infrastructure.config import settings
from app.infrastructure.env import is_production_env
from app.infrastructure.observability.logging import set_request_route, set_request_tenant_id, set_request_user_id
from app.infrastructure.security.jwt_verify import decode_access_token
from app.rag.kg.enterprise_ontology.edo_source import edo_authorization

_TENANT_ID = TypeAdapter(UUID)


async def bind_edo_authorization(
    credential: Annotated[str | None, Header(alias="X-EDO-Authorization")] = None,
) -> AsyncIterator[None]:
    with edo_authorization(credential):
        yield


def _parse_tenant_header(header: str) -> UUID:
    try:
        return _TENANT_ID.validate_python(header.strip())
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail="Invalid X-Tenant-ID header") from exc


async def get_current_account_id(request: Request) -> str:
    """Verify one request's credentials once, including direct asset-route calls."""
    if hasattr(request.state, "authenticated_account_id"):
        return request.state.authenticated_account_id
    headers = AuthHeaders(
        authorization=request.headers.get("Authorization"),
        x_user_id=request.headers.get("X-User-ID"),
        x_tenant_id=request.headers.get(settings.TENANT_HEADER),
    )
    if settings.AUTH_MODE == "header":
        if not headers.x_user_id or not headers.x_user_id.strip():
            raise HTTPException(status_code=401, detail="X-User-ID header required")
        account_id = headers.x_user_id.strip()
    else:
        authorization = headers.authorization
        if not authorization:
            raise HTTPException(status_code=401, detail="Authorization header required")
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not token.strip():
            raise HTTPException(status_code=401, detail="Invalid token")
        try:
            payload = await decode_access_token(token.strip())
        except ExpiredSignatureError as exc:
            raise HTTPException(status_code=401, detail="Token expired") from exc
        except InvalidTokenError as exc:
            raise HTTPException(status_code=401, detail="Invalid token") from exc
        account_id = payload["sub"]
        if not account_id.strip():
            raise HTTPException(status_code=401, detail="Invalid token")
        request.state.jwt_payload = payload
    request.state.authenticated_account_id = account_id
    request.state.user_id = account_id
    set_request_user_id(account_id)
    return account_id


async def get_tenant_id(request: Request) -> UUID:
    """Prefer verified token scope and keep untrusted tenant headers out of production."""
    await get_current_account_id(request)
    if hasattr(request.state, "tenant_id"):
        return request.state.tenant_id
    header = request.headers.get(settings.TENANT_HEADER)
    claim = settings.JWT_TENANT_CLAIM.strip()
    payload = request.state.jwt_payload if settings.AUTH_MODE == "jwt" else {}
    raw_tenant = payload.get(claim) if claim else None
    if raw_tenant is not None:
        try:
            tenant_id = _TENANT_ID.validate_python(raw_tenant)
        except ValidationError as exc:
            raise HTTPException(status_code=401, detail="Invalid token") from exc
        if settings.JWT_ENFORCE_TENANT_HEADER_MATCH:
            if not header:
                raise HTTPException(status_code=400, detail="X-Tenant-ID header required")
            if _parse_tenant_header(header) != tenant_id:
                raise HTTPException(status_code=401, detail="Invalid token")
        source = "jwt"
    else:
        if settings.AUTH_MODE == "jwt" and settings.JWT_ENFORCE_TENANT_HEADER_MATCH:
            raise HTTPException(status_code=401, detail="Invalid token")
        if header:
            tenant_id = _parse_tenant_header(header)
            if (
                settings.AUTH_MODE == "jwt"
                and is_production_env()
                and not settings.TENANT_HEADER_TRUSTED
                and tenant_id != UUID(settings.DEFAULT_TENANT_ID)
            ):
                raise HTTPException(status_code=400, detail="Untrusted X-Tenant-ID header")
            source = "header"
        else:
            tenant_id = UUID(settings.DEFAULT_TENANT_ID)
            source = "default"
    request.state.tenant_id = tenant_id
    request.state.tenant_id_source = source
    request.state.client_host = request.client.host if request.client is not None else None
    set_request_tenant_id(str(tenant_id))
    return tenant_id


async def bind_route_context(request: Request) -> None:
    """Bind the matched route template after FastAPI resolves the route."""
    route = request.scope["route"]
    set_request_route(route.path)


__all__ = ["bind_route_context", "get_current_account_id", "get_tenant_id"]
