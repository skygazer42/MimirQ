"""Resolve tenant and account identity for document asset requests."""

from collections.abc import Awaitable, Callable
from uuid import UUID

from fastapi import HTTPException, Request

from app.api.dependencies.auth import get_current_account_id_from_headers
from app.api.dependencies.tenant import _preferred_jwt_tenant_id
from app.core.config import settings
from app.core.env import is_production_env

Authenticator = Callable[..., Awaitable[str]]
TenantResolver = Callable[[Request], Awaitable[UUID | None]]


def _parse_tenant_id(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid tenant id") from exc


def _explicit_tenant_id(request: Request) -> UUID | None:
    tenant_header = (settings.TENANT_HEADER or "X-Tenant-ID").strip() or "X-Tenant-ID"
    raw = (request.headers.get(tenant_header) or "").strip()
    if not raw and tenant_header.lower() != "x-tenant-id":
        raw = (request.headers.get("x-tenant-id") or "").strip()
    if raw:
        return _parse_tenant_id(raw)

    for key in ("tenant_id", "x_tenant_id", "tenant"):
        raw = (request.query_params.get(key) or "").strip()
        if raw:
            return _parse_tenant_id(raw)
    return None


def _asset_request_header_account(request: Request, *, is_production: bool) -> str | None:
    account_id = (request.headers.get("x-user-id") or "").strip() or None
    if account_id is None and (is_production or not settings.ASSET_HEADER_AUTH_ALLOW_ANONYMOUS):
        raise HTTPException(status_code=401, detail="X-User-ID header required")
    return account_id


def _asset_request_authorization(request: Request) -> str:
    authorization = (request.headers.get("authorization") or "").strip()
    if not authorization:
        raise HTTPException(status_code=401, detail="Authentication required")
    return authorization


async def _verified_jwt_tenant_id(request: Request) -> UUID | None:
    return await _preferred_jwt_tenant_id(request)


async def _resolve_account_id_for_asset_request(
    request: Request,
    *,
    tenant_id: UUID | None = None,
    authenticator: Authenticator | None = None,
) -> str | None:
    if (settings.AUTH_MODE or "jwt").lower() == "header":
        return _asset_request_header_account(request, is_production=is_production_env())

    authorization = _asset_request_authorization(request)
    tenant_value = str(tenant_id) if tenant_id is not None else None
    try:
        resolve_account = authenticator or get_current_account_id_from_headers
        return await resolve_account(
            authorization=authorization,
            x_user_id=None,
            x_tenant_id=tenant_value,
        )
    except HTTPException:
        raise HTTPException(status_code=401, detail="Authentication required") from None


async def _resolve_tenant_id_for_asset_request(
    request: Request,
    *,
    fallback_tenant_id: UUID | None = None,
    conflict_detail: str = "Asset access denied for this tenant",
    tenant_resolver: TenantResolver | None = None,
) -> UUID:
    provided_tenant_id = _explicit_tenant_id(request)
    resolve_tenant = tenant_resolver or _verified_jwt_tenant_id
    verified_tenant_id = await resolve_tenant(request)
    if verified_tenant_id is not None:
        for candidate in (provided_tenant_id, fallback_tenant_id):
            if candidate is not None and candidate != verified_tenant_id:
                raise HTTPException(status_code=403, detail=conflict_detail)
        return verified_tenant_id

    if fallback_tenant_id is not None:
        if provided_tenant_id is not None and provided_tenant_id != fallback_tenant_id:
            raise HTTPException(status_code=403, detail=conflict_detail)
        return fallback_tenant_id
    if provided_tenant_id is not None:
        return provided_tenant_id
    if is_production_env():
        tenant_header = (settings.TENANT_HEADER or "X-Tenant-ID").strip() or "X-Tenant-ID"
        raise HTTPException(status_code=400, detail=f"{tenant_header} header or tenant_id query param required")
    return _parse_tenant_id(settings.DEFAULT_TENANT_ID)


async def resolve_asset_actor(
    request: Request,
    *,
    authenticator: Authenticator | None = None,
    tenant_resolver: TenantResolver | None = None,
) -> tuple[UUID, str | None]:
    tenant_id = await _resolve_tenant_id_for_asset_request(request, tenant_resolver=tenant_resolver)
    account_id = await _resolve_account_id_for_asset_request(request, tenant_id=tenant_id, authenticator=authenticator)
    return tenant_id, account_id


async def resolve_image_url_asset_actor(
    request: Request,
    *,
    fallback_tenant_id: UUID | None,
    conflict_detail: str,
    authenticator: Authenticator | None = None,
    tenant_resolver: TenantResolver | None = None,
) -> tuple[UUID, str | None]:
    tenant_id = await _resolve_tenant_id_for_asset_request(
        request,
        fallback_tenant_id=fallback_tenant_id,
        conflict_detail=conflict_detail,
        tenant_resolver=tenant_resolver,
    )
    account_id = await _resolve_account_id_for_asset_request(request, tenant_id=tenant_id, authenticator=authenticator)
    return tenant_id, account_id


__all__ = ["resolve_asset_actor", "resolve_image_url_asset_actor"]
