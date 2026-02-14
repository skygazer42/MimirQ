"""
Security headers middleware.

This is a lightweight, backend-only hardening layer inspired by common SaaS
knowledge-base deployments:
- Prevent MIME sniffing
- Reduce clickjacking risk
- Keep referrer data minimal by default
"""

from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
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
        self.x_content_type_options = str(x_content_type_options or "").strip()
        self.x_frame_options = str(x_frame_options or "").strip()
        self.referrer_policy = str(referrer_policy or "").strip()
        self.strict_transport_security = str(strict_transport_security or "").strip()
        self.permissions_policy = str(permissions_policy or "").strip()
        self.cross_origin_opener_policy = str(cross_origin_opener_policy or "").strip()
        self.cross_origin_resource_policy = str(cross_origin_resource_policy or "").strip()

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
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
