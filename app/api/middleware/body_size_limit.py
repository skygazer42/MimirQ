"""Hard request-body size limit for both fixed and streamed uploads."""

from collections.abc import Awaitable, Callable
from typing import Any

from starlette.responses import JSONResponse
from starlette.status import HTTP_413_CONTENT_TOO_LARGE
from starlette.types import Message, Receive, Scope, Send


class _BodyTooLargeError(Exception):
    pass


class BodySizeLimitMiddleware:
    def __init__(self, app: Callable[..., Awaitable[Any]], *, max_body_bytes: int = 0) -> None:
        self.app = app
        self.max_body_bytes = max(0, int(max_body_bytes or 0))

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        limit = self.max_body_bytes
        if scope["type"] != "http" or limit <= 0:
            await self.app(scope, receive, send)
            return

        for name, value in scope.get("headers", []):
            if name.lower() != b"content-length":
                continue
            try:
                if int(value) > limit:
                    await self._reject(scope, receive, send)
                    return
            except ValueError:
                pass
            break

        size = 0

        async def limited_receive() -> Message:
            nonlocal size
            message = await receive()
            if message["type"] == "http.request":
                size += len(message.get("body", b""))
                if size > limit:
                    raise _BodyTooLargeError
            return message

        try:
            await self.app(scope, limited_receive, send)
        except _BodyTooLargeError:
            await self._reject(scope, receive, send)

    @staticmethod
    async def _reject(scope: Scope, receive: Receive, send: Send) -> None:
        response = JSONResponse(
            status_code=HTTP_413_CONTENT_TOO_LARGE,
            content={"detail": "Request body too large"},
        )
        await response(scope, receive, send)
