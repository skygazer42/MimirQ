"""Request dependencies for the local account and workspace context."""

from uuid import UUID

from fastapi import Request

from app.core.config import settings
from app.core.logging_config import set_request_route, set_request_tenant_id, set_request_user_id


async def get_current_account_id(request: Request) -> str:
    """Bind the configured local account to the request and logging context."""
    account_id = "local"
    request.state.user_id = account_id
    set_request_user_id(account_id)
    return account_id


async def get_tenant_id(request: Request) -> UUID:
    """Bind the configured workspace to the request and logging context."""
    tenant_id = UUID(settings.DEFAULT_TENANT_ID)
    request.state.tenant_id = tenant_id
    set_request_tenant_id(str(tenant_id))
    return tenant_id


async def bind_route_context(request: Request) -> None:
    """Bind the matched route template after FastAPI resolves the route."""
    route = request.scope["route"]
    set_request_route(route.path)


__all__ = ["bind_route_context", "get_current_account_id", "get_tenant_id"]
