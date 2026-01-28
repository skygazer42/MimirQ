"""
Security headers middleware.

This is a lightweight, backend-only hardening layer inspired by common SaaS
knowledge-base products (Dify/RAGFlow/FastGPT style deployments):
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
    ) -> None:
        super().__init__(app)
        self.x_content_type_options = str(x_content_type_options or "").strip()
        self.x_frame_options = str(x_frame_options or "").strip()
        self.referrer_policy = str(referrer_policy or "").strip()

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)

        if self.x_content_type_options and "X-Content-Type-Options" not in response.headers:
            response.headers["X-Content-Type-Options"] = self.x_content_type_options
        if self.x_frame_options and "X-Frame-Options" not in response.headers:
            response.headers["X-Frame-Options"] = self.x_frame_options
        if self.referrer_policy and "Referrer-Policy" not in response.headers:
            response.headers["Referrer-Policy"] = self.referrer_policy

        return response

