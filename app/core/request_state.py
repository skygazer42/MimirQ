"""
Request-scoped state context.

This module exposes `request.state` (Starlette/FastAPI) to deeper service layers
via a contextvar, without threading a `Request` object through every call.

Primary use-case: request-scoped caches (e.g. tenant group membership lookups).
"""


import contextvars
from typing import Any

_request_state: contextvars.ContextVar[Any | None] = contextvars.ContextVar("mimirq.request_state", default=None)


def bind_request_state(state: Any | None) -> contextvars.Token[Any | None]:
    return _request_state.set(state)


def reset_request_state(token: contextvars.Token[Any | None]) -> None:
    try:
        _request_state.reset(token)
    except (LookupError, ValueError):
        # Best-effort: never fail request processing due to cleanup issues.
        return


def get_request_state() -> Any | None:
    return _request_state.get()


__all__ = ["bind_request_state", "reset_request_state", "get_request_state"]

