"""
Security headers middleware.

This is a lightweight, backend-only hardening layer inspired by common SaaS
knowledge-base deployments:
- Prevent MIME sniffing
- Reduce clickjacking risk
- Keep referrer data minimal by default
"""

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app: ASGIApp,
        *,
        x_content_type_options: str = "nosniff",
        x_frame_options: str = "DENY",
        referrer_policy: str = "strict-origin-when-cross-origin",
        strict_transport_security: str = "",
        permissions_policy: str = "",
        cross_origin_opener_policy: str = "",
        cross_origin_resource_policy: str = "",
    ) -> None:
        super().__init__(app)
        self.x_content_type_options = (x_content_type_options).strip()
        self.x_frame_options = (x_frame_options).strip()
        self.referrer_policy = (referrer_policy).strip()
        self.strict_transport_security = (strict_transport_security).strip()
        self.permissions_policy = (permissions_policy).strip()
        self.cross_origin_opener_policy = (cross_origin_opener_policy).strip()
        self.cross_origin_resource_policy = (cross_origin_resource_policy).strip()

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)

        if self.x_content_type_options and "X-Content-Type-Options" not in response.headers:
            response.headers["X-Content-Type-Options"] = self.x_content_type_options
        if self.x_frame_options and "X-Frame-Options" not in response.headers:
            response.headers["X-Frame-Options"] = self.x_frame_options
        if self.referrer_policy and "Referrer-Policy" not in response.headers:
            response.headers["Referrer-Policy"] = self.referrer_policy

        if self.strict_transport_security and "Strict-Transport-Security" not in response.headers:
            response.headers["Strict-Transport-Security"] = self.strict_transport_security
        if self.permissions_policy and "Permissions-Policy" not in response.headers:
            response.headers["Permissions-Policy"] = self.permissions_policy
        if self.cross_origin_opener_policy and "Cross-Origin-Opener-Policy" not in response.headers:
            response.headers["Cross-Origin-Opener-Policy"] = self.cross_origin_opener_policy
        if self.cross_origin_resource_policy and "Cross-Origin-Resource-Policy" not in response.headers:
            response.headers["Cross-Origin-Resource-Policy"] = self.cross_origin_resource_policy

        return response
