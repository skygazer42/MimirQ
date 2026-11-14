"""Token-bucket rate limiters shared by HTTP and tenant quota enforcement."""

import asyncio
import time
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

from app.rag.core.logging import get_logger

logger = get_logger("core.rate_limit")


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
        self.burst_size = int(self.requests_per_second * 2) if burst_size is None else int(burst_size)
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
        self.redis_url = redis_url.strip()
        self.namespace = namespace
        self.requests_per_second = float(requests_per_second)
        self.burst_size = int(self.requests_per_second * 2) if burst_size is None else int(burst_size)
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
            wait_time = float(wait_raw)
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
        return await asyncio.to_thread(self.check, key)
