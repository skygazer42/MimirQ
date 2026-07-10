"""
Logging-related FastAPI dependencies.

These are used to enrich request-scoped structured logs (contextvars) with
low-cardinality fields like the route template.
"""


import asyncio

from fastapi import Request

from app.core.logging_config import set_request_route


async def _yield_to_event_loop() -> None:
    loop = asyncio.get_running_loop()
    ready = loop.create_future()
    loop.call_soon(ready.set_result, None)
    await ready


async def bind_route_context(request: Request) -> None:
    """
    Bind the current request's route template (best-effort).

    Notes:
    - This runs after routing, so `request.scope["route"]` should typically be set.
    - We prefer route templates (e.g. `/api/v1/rag/retrieve`) over raw paths to avoid
      high-cardinality logs (e.g. `/api/v1/documents/<uuid>`).
    """
    await _yield_to_event_loop()
    route = request.scope.get("route")
    template = getattr(route, "path", None)
    if template:
        set_request_route(str(template))
        return

    # Fallback to raw path when routing information isn't available.
    set_request_route(str(request.scope.get("path") or ""))


__all__ = ["bind_route_context"]
