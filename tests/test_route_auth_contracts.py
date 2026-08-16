import builtins

import starlette.status as _starlette_status
from fastapi.routing import APIRoute
from pydantic import ConfigDict as _PydanticConfigDict

if not hasattr(_starlette_status, "HTTP_413_CONTENT_TOO_LARGE"):
    _starlette_status.HTTP_413_CONTENT_TOO_LARGE = _starlette_status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
if not hasattr(_starlette_status, "HTTP_422_UNPROCESSABLE_CONTENT"):
    _starlette_status.HTTP_422_UNPROCESSABLE_CONTENT = _starlette_status.HTTP_422_UNPROCESSABLE_ENTITY
if not hasattr(builtins, "ConfigDict"):
    builtins.ConfigDict = _PydanticConfigDict

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.v1.document_assets import _authorize_bound_preview_document
from app.api.v1.integrations_dify import _require_dify_actor
from app.api.v1.metrics import require_metrics_access
from app.api.v1.scim import _require_scim_actor
from app.main import app

_PUBLIC_API_PATHS = {
    "/api/v1/health",
    "/api/v1/health/ready",
    "/api/v1/meta",
    "/api/v1/auth/register",
    "/api/v1/auth/login",
    "/api/v1/auth/saml/exchange",
    "/api/v1/auth/saml/bridge/consume",
    "/api/v1/auth/saml/metadata",
}

# Browser asset requests cannot reliably attach the normal API headers. These
# handlers resolve tenant/account context internally and enforce document or
# preview-owner bindings before returning bytes.
_SELF_AUTHORIZING_API_PATHS = {
    "/api/v1/documents/{document_id}/download",
    "/api/v1/documents/image/{image_id}",
    "/api/v1/documents/image-url/{img_id}",
}

_AUTH_CALLS = {
    get_current_account_id,
    get_tenant_id,
    _require_scim_actor,
    _require_dify_actor,
    require_metrics_access,
    _authorize_bound_preview_document,
}


def _dependency_closure(route: APIRoute) -> list[object]:
    calls: list[object] = []
    stack = list(getattr(route.dependant, "dependencies", []) or [])
    seen: set[int] = set()
    while stack:
        dependency = stack.pop()
        marker = id(dependency)
        if marker in seen:
            continue
        seen.add(marker)
        call = getattr(dependency, "call", None)
        if call is not None:
            calls.append(call)
        stack.extend(getattr(dependency, "dependencies", []) or [])
    return calls


def test_api_routes_require_explicit_auth_dependencies() -> None:
    missing: list[str] = []

    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if not route.path.startswith("/api/"):
            continue
        if route.path in _PUBLIC_API_PATHS or route.path in _SELF_AUTHORIZING_API_PATHS:
            continue

        dependency_calls = _dependency_closure(route)
        if not any(call in _AUTH_CALLS for call in dependency_calls):
            names = sorted({getattr(call, "__name__", repr(call)) for call in dependency_calls})
            methods = ",".join(sorted(route.methods or []))
            missing.append(f"{methods} {route.path} deps={names}")

    assert missing == [], "Unauthenticated /api routes found:\n" + "\n".join(missing)


def test_auth_contract_exception_lists_are_explicit_and_current() -> None:
    api_paths = {
        route.path
        for route in app.routes
        if isinstance(route, APIRoute) and route.path.startswith("/api/")
    }

    assert _PUBLIC_API_PATHS.isdisjoint(_SELF_AUTHORIZING_API_PATHS)
    assert (_PUBLIC_API_PATHS | _SELF_AUTHORIZING_API_PATHS) <= api_paths
