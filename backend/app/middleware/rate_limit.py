"""
Rate limiting middleware for FastAPI.

Token-bucket rate limiting with:
- Per-IP / per-user keying
- Configurable limits via settings
- Thread-safe implementation
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Callable, Dict, Optional, Tuple

from fastapi import HTTPException, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.status import HTTP_429_TOO_MANY_REQUESTS

logger = logging.getLogger(__name__)


@dataclass
class TokenBucket:
    capacity: float
    refill_rate: float  # tokens per second
    tokens: float = field(default=None)
    last_refill: float = field(default_factory=time.time)
    lock: Lock = field(default_factory=Lock)

    def __post_init__(self) -> None:
        if self.tokens is None:
            self.tokens = self.capacity

    def consume(self, tokens: float = 1) -> Tuple[bool, float]:
        with self.lock:
            now = time.time()
            elapsed = now - self.last_refill
            self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
            self.last_refill = now

            if self.tokens >= tokens:
                self.tokens -= tokens
                return True, 0.0

            needed = tokens - self.tokens
            wait_time = needed / self.refill_rate if self.refill_rate > 0 else 60.0
            return False, wait_time


class RateLimiter:
    def __init__(
        self,
        requests_per_second: float = 10.0,
        burst_size: Optional[int] = None,
        cleanup_interval: float = 60.0,
    ) -> None:
        self.requests_per_second = float(requests_per_second)
        self.burst_size = int(burst_size or int(self.requests_per_second * 2))
        self.cleanup_interval = float(cleanup_interval)
        self._buckets: Dict[str, TokenBucket] = {}
        self._global_lock = Lock()
        self._last_cleanup = time.time()

    def _get_bucket(self, key: str) -> TokenBucket:
        with self._global_lock:
            now = time.time()
            if now - self._last_cleanup > self.cleanup_interval:
                self._cleanup_old_buckets(now)
                self._last_cleanup = now

            if key not in self._buckets:
                self._buckets[key] = TokenBucket(
                    capacity=float(self.burst_size),
                    refill_rate=self.requests_per_second,
                )
            return self._buckets[key]

    def _cleanup_old_buckets(self, now: float) -> None:
        stale_keys = []
        for key, bucket in self._buckets.items():
            if bucket.tokens >= bucket.capacity * 0.99 and now - bucket.last_refill > self.cleanup_interval * 2:
                stale_keys.append(key)

        for key in stale_keys:
            del self._buckets[key]

        if stale_keys:
            logger.debug("Cleaned up %d stale rate limit buckets", len(stale_keys))

    def check(self, key: str) -> Tuple[bool, float]:
        bucket = self._get_bucket(key)
        return bucket.consume(1)

    async def acheck(self, key: str) -> Tuple[bool, float]:
        return self.check(key)


_default_limiter: Optional[RateLimiter] = None


def get_default_limiter() -> RateLimiter:
    global _default_limiter
    if _default_limiter is None:
        from app.core.config import settings

        _default_limiter = RateLimiter(
            requests_per_second=getattr(settings, "RATE_LIMIT_REQUESTS_PER_SECOND", 10.0),
            burst_size=getattr(settings, "RATE_LIMIT_BURST_SIZE", 20),
        )
    return _default_limiter


def get_client_key(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        client_ip = forwarded.split(",")[0].strip()
    else:
        client_ip = request.client.host if request.client else "unknown"

    user_id = getattr(request.state, "user_id", None)
    if user_id:
        return f"user:{user_id}"
    return f"ip:{client_ip}"


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        requests_per_second: float = 10.0,
        burst_size: Optional[int] = None,
        exclude_paths: Optional[list] = None,
    ) -> None:
        super().__init__(app)
        self.limiter = RateLimiter(
            requests_per_second=requests_per_second,
            burst_size=burst_size,
        )
        self.exclude_paths = set(exclude_paths or ["/health", "/", "/docs", "/openapi.json", "/redoc"])

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.url.path in self.exclude_paths:
            return await call_next(request)

        key = get_client_key(request)
        allowed, retry_after = await self.limiter.acheck(key)
        if not allowed:
            logger.warning("Rate limit exceeded for %s on %s", key, request.url.path)
            return JSONResponse(
                status_code=HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "detail": "Too many requests. Please try again later.",
                    "retry_after": round(retry_after, 2),
                },
                headers={"Retry-After": str(int(retry_after) + 1)},
            )

        return await call_next(request)


async def rate_limit_dependency(
    request: Request,
    limiter: Optional[RateLimiter] = None,
) -> None:
    if limiter is None:
        limiter = get_default_limiter()

    key = get_client_key(request)
    allowed, retry_after = await limiter.acheck(key)
    if not allowed:
        raise HTTPException(
            status_code=HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "message": "Too many requests. Please try again later.",
                "retry_after": round(retry_after, 2),
            },
            headers={"Retry-After": str(int(retry_after) + 1)},
        )

