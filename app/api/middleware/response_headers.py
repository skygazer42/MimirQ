"""Response security defaults and server fingerprint removal."""

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp


class ResponseSecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Set configured security headers without overriding route-specific values."""

    def __init__(
        self,
        app: ASGIApp,
        *,
        x_content_type_options: str,
        x_frame_options: str,
        referrer_policy: str,
        strict_transport_security: str,
        permissions_policy: str,
        cross_origin_opener_policy: str,
        cross_origin_resource_policy: str,
    ) -> None:
        super().__init__(app)
        configured_headers = {
            "X-Content-Type-Options": x_content_type_options,
            "X-Frame-Options": x_frame_options,
            "Referrer-Policy": referrer_policy,
            "Strict-Transport-Security": strict_transport_security,
            "Permissions-Policy": permissions_policy,
            "Cross-Origin-Opener-Policy": cross_origin_opener_policy,
            "Cross-Origin-Resource-Policy": cross_origin_resource_policy,
        }
        self.response_headers = {name: value.strip() for name, value in configured_headers.items() if value.strip()}

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        for name, value in self.response_headers.items():
            response.headers.setdefault(name, value)
        return response


class ResponseFingerprintSanitizerMiddleware(BaseHTTPMiddleware):
    """Remove server implementation headers from every response."""

    _FINGERPRINT_HEADERS = ("Server", "X-Powered-By", "X-AspNet-Version", "X-AspNetMvc-Version")

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        for name in self._FINGERPRINT_HEADERS:
            del response.headers[name]
        return response


__all__ = ["ResponseFingerprintSanitizerMiddleware", "ResponseSecurityHeadersMiddleware"]
