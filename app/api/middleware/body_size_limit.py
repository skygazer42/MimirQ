"""限制 HTTP 请求体大小，保持上传按块读取。"""

from starlette.datastructures import Headers
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse
from starlette.status import HTTP_400_BAD_REQUEST, HTTP_413_CONTENT_TOO_LARGE
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class BodySizeLimitMiddleware:
    """检查声明长度和实际读取量，读取超限交给 FastAPI 的异常处理层。"""

    def __init__(self, app: ASGIApp, *, max_body_bytes: int) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        max_body_bytes = self.max_body_bytes
        if scope["type"] != "http" or max_body_bytes <= 0:
            await self.app(scope, receive, send)
            return

        content_length = Headers(scope=scope).get("content-length")
        if content_length is not None:
            if not content_length.isdecimal():
                response = JSONResponse(
                    status_code=HTTP_400_BAD_REQUEST,
                    content={"detail": "Invalid Content-Length"},
                )
                await response(scope, receive, send)
                return
            if int(content_length) > max_body_bytes:
                response = JSONResponse(
                    status_code=HTTP_413_CONTENT_TOO_LARGE,
                    content={"detail": "Request body too large"},
                )
                await response(scope, receive, send)
                return

        received_bytes = 0

        async def receive_with_limit() -> Message:
            nonlocal received_bytes
            message = await receive()
            if message["type"] == "http.request":
                received_bytes += len(message.get("body", b""))
                if received_bytes > max_body_bytes:
                    raise HTTPException(
                        status_code=HTTP_413_CONTENT_TOO_LARGE,
                        detail="Request body too large",
                    )
            return message

        await self.app(scope, receive_with_limit, send)
