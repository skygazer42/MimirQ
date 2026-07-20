"""
Request rate limiting middleware

Token bucket algorithm based FastAPI request rate limiting:
- Supports rate limiting by IP or user ID
- Configurable rate limit parameters
- Thread-safe implementation
"""
import asyncio
import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

from fastapi import HTTPException, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.status import HTTP_429_TOO_MANY_REQUESTS

from app.core import jwt_verify
from app.core.config import settings
from app.rag.core.logging import get_logger

logger = get_logger("api.rate_limit")


@dataclass
class TokenBucket:
    capacity: float
    refill_rate: float  # tokens per second
    tokens: float = field(default=None)
    # Use monotonic time to avoid clock jumps affecting rate calculations.
    last_refill: float = field(default_factory=time.monotonic)
    lock: Lock = field(default_factory=Lock)

    def __post_init__(self) -> None:
        if self.tokens is None:
            self.tokens = self.capacity

    def consume(self, tokens: float = 1) -> tuple[bool, float]:
        with self.lock:
            now = time.monotonic()
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
        burst_size: int | None = None,
        cleanup_interval: float = 60.0,
    ) -> None:
        self.requests_per_second = float(requests_per_second)
        self.burst_size = int(burst_size or int(self.requests_per_second * 2))
        self.cleanup_interval = float(cleanup_interval)
        self._buckets: dict[str, TokenBucket] = {}
        self._global_lock = Lock()
        self._last_cleanup = time.monotonic()

    def _get_bucket(self, key: str) -> TokenBucket:
        with self._global_lock:
            now = time.monotonic()
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

    def check(self, key: str) -> tuple[bool, float]:
        bucket = self._get_bucket(key)
        return bucket.consume(1)

    async def acheck(self, key: str) -> tuple[bool, float]:
        await asyncio.sleep(0)
        return self.check(key)


_REDIS_BUCKET_LUA = r"""
local key = KEYS[1]
local capacity = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local requested = tonumber(ARGV[4])
local ttl = tonumber(ARGV[5])

local values = redis.call("HMGET", key, "tokens", "ts")
local tokens = tonumber(values[1])
local ts = tonumber(values[2])

if not tokens then tokens = capacity end
if not ts then ts = now end

local delta = now - ts
if delta < 0 then delta = 0 end

tokens = math.min(capacity, tokens + delta * refill_rate)

local allowed = 0
local wait = 0
if refill_rate <= 0 then
  allowed = 1
else
  if tokens >= requested then
    tokens = tokens - requested
    allowed = 1
  else
    local needed = requested - tokens
    wait = needed / refill_rate
  end
end

redis.call("HMSET", key, "tokens", tokens, "ts", now)
redis.call("EXPIRE", key, ttl)
return {allowed, wait}
"""


class RedisRateLimiter:
    """
    Redis-backed token bucket limiter (distributed across processes/instances).

    Fail-open: when Redis is unavailable, allow requests to avoid turning an outage
    into a full API downtime.
    """

    def __init__(
        self,
        *,
        redis_url: str,
        namespace: str,
        requests_per_second: float = 10.0,
        burst_size: int | None = None,
        key_prefix: str = "rl",
        key_ttl_sec: int = 600,
    ) -> None:
        self.redis_url = str(redis_url or "").strip()
        self.namespace = str(namespace or "default").strip() or "default"
        self.requests_per_second = float(requests_per_second)
        self.burst_size = int(burst_size or int(self.requests_per_second * 2))
        self.key_prefix = str(key_prefix or "rl").strip() or "rl"
        self.key_ttl_sec = max(10, int(key_ttl_sec or 0) or 600)
        self._client: Any | None = None
        self._token_bucket_script: Any | None = None
        self._last_error_ts = 0.0

    def _get_client(self) -> Any:
        if self._client is None:
            import redis

            self._client = redis.Redis.from_url(
                self.redis_url,
                socket_timeout=1,
                socket_connect_timeout=1,
                decode_responses=True,
            )
        return self._client

    def _get_token_bucket_script(self, client: Any) -> Any:
        if self._token_bucket_script is None:
            self._token_bucket_script = client.register_script(_REDIS_BUCKET_LUA)
        return self._token_bucket_script

    def _redis_key(self, key: str) -> str:
        return f"{self.key_prefix}:{self.namespace}:{key}"

    def check(self, key: str) -> tuple[bool, float]:
        if not self.redis_url:
            return True, 0.0

        now = time.time()
        redis_key = self._redis_key(key)
        try:
            client = self._get_client()
            script = self._get_token_bucket_script(client)
            allowed_raw, wait_raw = script(
                keys=[redis_key],
                args=[
                    float(self.burst_size),
                    float(self.requests_per_second),
                    float(now),
                    1.0,
                    float(self.key_ttl_sec),
                ],
            )
            allowed = int(allowed_raw) == 1
            wait_time = float(wait_raw or 0.0)
            return (True, 0.0) if allowed else (False, max(0.0, wait_time))
        except Exception as exc:  # noqa: BLE001
            self._client = None
            self._token_bucket_script = None
            # Avoid log spam during outages.
            if now - self._last_error_ts > 60:
                self._last_error_ts = now
                logger.warning("Redis rate limiter error (fail-open): %s", str(exc)[:200])
            return True, 0.0

    async def acheck(self, key: str) -> tuple[bool, float]:
        await asyncio.sleep(0)
        return self.check(key)


_default_limiter: RateLimiter | RedisRateLimiter | None = None


def get_default_limiter() -> RateLimiter | RedisRateLimiter:
    global _default_limiter
    if _default_limiter is None:
        from app.core.config import settings

        if bool(getattr(settings, "RATE_LIMIT_REDIS_ENABLED", False)) and bool(getattr(settings, "REDIS_URL", "")):
            _default_limiter = RedisRateLimiter(
                redis_url=str(getattr(settings, "REDIS_URL", "") or ""),
                namespace="default",
                requests_per_second=getattr(settings, "RATE_LIMIT_REQUESTS_PER_SECOND", 10.0),
                burst_size=getattr(settings, "RATE_LIMIT_BURST_SIZE", 20),
                key_prefix=str(getattr(settings, "RATE_LIMIT_REDIS_PREFIX", "rl") or "rl"),
                key_ttl_sec=int(getattr(settings, "RATE_LIMIT_REDIS_KEY_TTL_SEC", 600) or 600),
            )
        else:
            _default_limiter = RateLimiter(
                requests_per_second=getattr(settings, "RATE_LIMIT_REQUESTS_PER_SECOND", 10.0),
                burst_size=getattr(settings, "RATE_LIMIT_BURST_SIZE", 20),
            )
    return _default_limiter


def _client_ip_from_request(request: Request) -> str:
    if request.client:
        return request.client.host
    return "unknown"


def _tenant_id_from_request(request: Request) -> str:
    tenant_header = str(getattr(settings, "TENANT_HEADER", "") or "X-Tenant-ID").strip() or "X-Tenant-ID"
    tenant_id = (request.headers.get(tenant_header) or "").strip()
    if not tenant_id and tenant_header.lower() != "x-tenant-id":
        tenant_id = (request.headers.get("X-Tenant-ID") or "").strip()
    return tenant_id


def _jwt_bearer_token(request: Request) -> str:
    auth = (request.headers.get("Authorization") or "").strip()
    if not auth.lower().startswith("bearer "):
        return ""
    return auth[7:].strip()


def _tenant_id_from_jwt_payload(payload: dict[str, Any]) -> str:
    claim = str(getattr(settings, "JWT_TENANT_CLAIM", "") or "").strip()
    if not claim:
        return ""
    raw = payload.get(claim)
    return str(raw).strip() if raw else ""


async def _jwt_identity_from_request(request: Request) -> tuple[str, str]:
    token = _jwt_bearer_token(request)
    if not token:
        return "", ""
    try:
        payload = await jwt_verify.decode_access_token(token)
    except Exception:  # noqa: BLE001
        return "", ""
    return (payload.get("sub") or "").strip(), _tenant_id_from_jwt_payload(payload)


def _rate_limit_key(*, tenant_id: str, user_id: str, client_ip: str) -> str:
    if user_id:
        return f"tenant:{tenant_id}:user:{user_id}" if tenant_id else f"user:{user_id}"
    return f"tenant:{tenant_id}:ip:{client_ip}" if tenant_id else f"ip:{client_ip}"


async def get_client_key(request: Request) -> str:
    client_ip = _client_ip_from_request(request)
    tenant_id = _tenant_id_from_request(request)

    # Prefer a trusted user id:
    # - AUTH_MODE=jwt: JWT subject (ignore X-User-ID to avoid spoofing rate-limit keys)
    # - AUTH_MODE=header: X-User-ID (dev-only)
    user_id = str(getattr(request.state, "user_id", "") or "").strip()
    mode = (getattr(settings, "AUTH_MODE", "jwt") or "jwt").lower()

    if not user_id and mode == "header":
        user_id = (request.headers.get("X-User-ID") or "").strip()
    elif not user_id:
        user_id, token_tenant_id = await _jwt_identity_from_request(request)
        tenant_id = token_tenant_id or tenant_id

    return _rate_limit_key(tenant_id=tenant_id, user_id=user_id, client_ip=client_ip)


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        requests_per_second: float = 10.0,
        burst_size: int | None = None,
        chat_requests_per_second: float | None = None,
        chat_burst_size: int | None = None,
        chat_prefixes: list[str] | None = None,
        exclude_paths: list | None = None,
        exclude_prefixes: list[str] | None = None,
    ) -> None:
        super().__init__(app)

        use_redis = bool(getattr(settings, "RATE_LIMIT_REDIS_ENABLED", False)) and bool(getattr(settings, "REDIS_URL", ""))
        if use_redis:
            self.limiter = RedisRateLimiter(
                redis_url=str(getattr(settings, "REDIS_URL", "") or ""),
                namespace="default",
                requests_per_second=requests_per_second,
                burst_size=burst_size,
                key_prefix=str(getattr(settings, "RATE_LIMIT_REDIS_PREFIX", "rl") or "rl"),
                key_ttl_sec=int(getattr(settings, "RATE_LIMIT_REDIS_KEY_TTL_SEC", 600) or 600),
            )
        else:
            self.limiter = RateLimiter(
                requests_per_second=requests_per_second,
                burst_size=burst_size,
            )

        self.chat_limiter: RateLimiter | RedisRateLimiter | None = None
        if chat_requests_per_second is not None:
            if use_redis:
                self.chat_limiter = RedisRateLimiter(
                    redis_url=str(getattr(settings, "REDIS_URL", "") or ""),
                    namespace="chat",
                    requests_per_second=float(chat_requests_per_second),
                    burst_size=chat_burst_size,
                    key_prefix=str(getattr(settings, "RATE_LIMIT_REDIS_PREFIX", "rl") or "rl"),
                    key_ttl_sec=int(getattr(settings, "RATE_LIMIT_REDIS_KEY_TTL_SEC", 600) or 600),
                )
            else:
                self.chat_limiter = RateLimiter(
                    requests_per_second=float(chat_requests_per_second),
                    burst_size=chat_burst_size,
                )
        self.chat_prefixes = tuple(chat_prefixes or [])

        # Exclude high-fanout "asset-like" endpoints from rate limiting, otherwise the browser
        # may trip the limiter when rendering many images at once (e.g., DeepDoc/Docling previews).
        default_exclude_paths = [
            "/health",
            "/api/v1/health",
            "/api/v1/health/ready",
            "/",
            "/docs",
            "/openapi.json",
            "/redoc",
        ]
        default_exclude_prefixes = [
            "/api/v1/documents/image/",
            "/api/v1/documents/image-url/",
        ]

        self.exclude_paths = set(default_exclude_paths)
        if exclude_paths:
            self.exclude_paths |= set(exclude_paths)

        prefixes = list(default_exclude_prefixes)
        if exclude_prefixes:
            prefixes.extend(list(exclude_prefixes))
        # Normalize + dedupe while keeping stable order.
        seen: set[str] = set()
        ordered: list[str] = []
        for p in prefixes:
            val = str(p or "").strip()
            if not val:
                continue
            if val in seen:
                continue
            seen.add(val)
            ordered.append(val)
        self.exclude_prefixes = tuple(ordered)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path
        if request.method.upper() == "OPTIONS":
            return await call_next(request)

        if path in self.exclude_paths or (self.exclude_prefixes and any(path.startswith(p) for p in self.exclude_prefixes)):
            return await call_next(request)

        key = await get_client_key(request)
        limiter = self.limiter
        if self.chat_limiter is not None and self.chat_prefixes:
            path = request.url.path
            if any(path.startswith(prefix) for prefix in self.chat_prefixes):
                limiter = self.chat_limiter

        allowed, retry_after = await limiter.acheck(key)
        if not allowed:
            retry_after_sec = max(1, int(math.ceil(float(retry_after or 0.0))))
            rate_scope = "chat" if limiter is self.chat_limiter else "api"
            logger.warning("Rate limit exceeded for %s on %s", key, request.url.path)

            from app.core.exceptions import ErrorResponse, get_request_id

            detail = {
                "retry_after_sec": retry_after_sec,
                "limit": float(getattr(limiter, "requests_per_second", 0.0) or 0.0),
                "scope": f"rate_limit:{rate_scope}",
            }
            return JSONResponse(
                status_code=HTTP_429_TOO_MANY_REQUESTS,
                headers={"Retry-After": str(retry_after_sec)},
                content=ErrorResponse(
                    error="RATE_LIMIT_EXCEEDED",
                    message="Too many requests. Please try again later.",
                    detail=detail,
                    request_id=get_request_id(request),
                    hint="You are being rate limited. Retry later, or reduce concurrent requests / embedding concurrency.",
                ).model_dump(exclude_none=True),
            )

        return await call_next(request)


async def rate_limit_dependency(
    request: Request,
    limiter: RateLimiter | RedisRateLimiter | None = None,
) -> None:
    if limiter is None:
        limiter = get_default_limiter()

    key = await get_client_key(request)
    allowed, retry_after = await limiter.acheck(key)
    if not allowed:
        retry_after_sec = max(1, int(math.ceil(float(retry_after or 0.0))))
        raise HTTPException(
            status_code=HTTP_429_TOO_MANY_REQUESTS,
            detail={
                "message": "Too many requests. Please try again later.",
                "retry_after_sec": retry_after_sec,
                "limit": float(getattr(limiter, "requests_per_second", 0.0) or 0.0),
                "scope": "api",
            },
            headers={"Retry-After": str(retry_after_sec)},
        )
