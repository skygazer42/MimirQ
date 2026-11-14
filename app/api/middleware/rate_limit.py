"""按客户端地址限制 API 和聊天请求的速率。"""

import math

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.status import HTTP_429_TOO_MANY_REQUESTS
from starlette.types import ASGIApp

from app.core.config import settings
from app.core.exceptions import ErrorResponse, get_request_id
from app.core.rate_limit import RateLimiter, RedisRateLimiter
from app.rag.core.logging import get_logger

logger = get_logger("api.rate_limit")

_RATE_LIMIT_EXCLUDED_PATHS = frozenset(
    {
        "/health",
        "/api/v1/health",
        "/api/v1/health/ready",
        "/",
        "/docs",
        "/openapi.json",
        "/redoc",
    }
)
_RATE_LIMIT_EXCLUDED_PREFIXES = ("/api/v1/documents/image/", "/api/v1/documents/image-url/")


def _create_rate_limiter(
    *, namespace: str, requests_per_second: float, burst_size: int, use_redis: bool
) -> RateLimiter | RedisRateLimiter:
    if use_redis:
        return RedisRateLimiter(
            redis_url=settings.REDIS_URL,
            namespace=namespace,
            requests_per_second=requests_per_second,
            burst_size=burst_size,
            key_prefix=settings.RATE_LIMIT_REDIS_PREFIX,
            key_ttl_sec=settings.RATE_LIMIT_REDIS_KEY_TTL_SEC,
        )
    return RateLimiter(requests_per_second=requests_per_second, burst_size=burst_size)


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app: ASGIApp,
        *,
        requests_per_second: float,
        burst_size: int,
        chat_requests_per_second: float,
        chat_burst_size: int,
        chat_route_prefixes: list[str],
    ) -> None:
        super().__init__(app)
        use_redis = settings.RATE_LIMIT_REDIS_ENABLED and bool(settings.REDIS_URL)
        self.limiter = _create_rate_limiter(
            namespace="default",
            requests_per_second=requests_per_second,
            burst_size=burst_size,
            use_redis=use_redis,
        )
        self.chat_limiter = _create_rate_limiter(
            namespace="chat",
            requests_per_second=chat_requests_per_second,
            burst_size=chat_burst_size,
            use_redis=use_redis,
        )
        self.chat_route_prefixes = tuple(chat_route_prefixes)

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        if (
            request.method == "OPTIONS"
            or path in _RATE_LIMIT_EXCLUDED_PATHS
            or path.startswith(_RATE_LIMIT_EXCLUDED_PREFIXES)
        ):
            return await call_next(request)

        client = request.client
        client_key = "ip:unknown" if client is None else f"ip:{client.host}"
        limiter = self.limiter
        rate_scope = "api"
        if path.startswith(self.chat_route_prefixes):
            limiter = self.chat_limiter
            rate_scope = "chat"

        allowed, retry_after = await limiter.acheck(client_key)
        if allowed:
            return await call_next(request)

        retry_after_seconds = max(1, math.ceil(retry_after))
        logger.warning("Rate limit exceeded for %s on %s", client_key, path)
        return JSONResponse(
            status_code=HTTP_429_TOO_MANY_REQUESTS,
            headers={"Retry-After": str(retry_after_seconds)},
            content=ErrorResponse(
                error="RATE_LIMIT_EXCEEDED",
                message="Too many requests. Please try again later.",
                detail={
                    "retry_after_sec": retry_after_seconds,
                    "limit": limiter.requests_per_second,
                    "scope": f"rate_limit:{rate_scope}",
                },
                request_id=get_request_id(request),
                hint="You are being rate limited. Retry later, or reduce concurrent requests / embedding concurrency.",
            ).model_dump(exclude_none=True),
        )
