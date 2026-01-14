from __future__ import annotations

import time
from typing import Any

from app.rag.core.logging import get_logger

logger = get_logger("tasks.locks")


def get_retry_exc():  # noqa: ANN201
    try:
        from arq import Retry  # type: ignore

        return Retry
    except Exception:  # noqa: BLE001
        return None


async def tenant_acquire(  # noqa: ANN201
    redis: Any,
    *,
    tenant_id: str,
    kind: str,
    limit: int,
    ttl_sec: int = 120,
    retry_defer_sec: int = 2,
):
    """
    Simple per-tenant concurrency limit (Redis counting semaphore).

    - If INCR > limit: roll back with DECR and raise arq.Retry (when available).
    - Returns a semaphore key string on success, else None.
    """
    if redis is None or limit <= 0:
        return None

    key = f"sem:tenant:{tenant_id}:{kind}"
    try:
        val = await redis.incr(key)
        await redis.expire(key, ttl_sec)
        if int(val) > int(limit):
            await redis.decr(key)
            Retry = get_retry_exc()
            if Retry:
                raise Retry(defer=int(retry_defer_sec))
            return None
        return key
    except Exception as exc:  # noqa: BLE001
        logger.warning("Tenant semaphore acquire failed (skip limit): %s", str(exc)[:200])
        return None


async def tenant_release(redis: Any, key: str | None) -> None:
    if redis is None or not key:
        return
    try:
        val = await redis.decr(key)
        if int(val) <= 0:
            await redis.delete(key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Tenant semaphore release failed: %s", str(exc)[:200])


async def acquire_lock(redis: Any, *, key: str, value: str, ttl_sec: int) -> bool:
    """
    Best-effort idempotency lock (Redis SET NX EX).

    Returns:
        True if lock acquired (or Redis unavailable)
        False if lock already held
    """
    if redis is None:
        return True
    try:
        acquired = await redis.set(key, value, ex=int(ttl_sec), nx=True)
        return bool(acquired)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis lock acquire failed (continue without lock): %s", str(exc)[:200])
        return True


async def release_lock(redis: Any, *, key: str, value: str) -> None:
    """
    Best-effort idempotency lock release.

    Only deletes the key when the stored value matches `value`.
    """
    if redis is None:
        return
    try:
        cur = await redis.get(key)
        cur_decoded = cur.decode("utf-8", "ignore") if isinstance(cur, (bytes, bytearray)) else cur
        if cur_decoded == value:
            await redis.delete(key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis lock release failed: %s", str(exc)[:200])


def make_lock_value(requested_by: str) -> str:
    return f"{requested_by}:{int(time.time())}"

