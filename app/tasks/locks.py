
import time
from typing import Any

from app.core.optional_deps import require_dependency
from app.rag.core.logging import get_logger

logger = get_logger("tasks.locks")


def get_retry_exc():  # noqa: ANN201
    # When task queue is enabled, Retry must exist; failing silently would bypass concurrency limits.
    mod = require_dependency("arq", feature="task_queue_retry")
    retry_cls = getattr(mod, "Retry", None)
    if retry_cls is None:
        # If arq is installed but doesn't expose Retry, it's likely a version mismatch.
        raise RuntimeError("arq is installed but Retry is missing (version mismatch?)")
    return retry_cls


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
    retry_cls = None
    try:
        retry_cls = get_retry_exc()
    except Exception:  # noqa: BLE001
        retry_cls = None
    try:
        val = await redis.incr(key)
        await redis.expire(key, ttl_sec)
        if int(val) > int(limit):
            await redis.decr(key)
            if retry_cls:
                raise retry_cls(defer=int(retry_defer_sec))
            return None
        return key
    except Exception as exc:  # noqa: BLE001
        if retry_cls is not None:
            try:
                if isinstance(exc, retry_cls):
                    raise
            except TypeError as exc:
                logger.debug("Ignoring non-critical task lock fallback failure: %s", exc)
        logger.warning("Tenant semaphore acquire failed (skip limit): %s", str(exc)[:200])
        return None


async def dataset_acquire(  # noqa: ANN201
    redis: Any,
    *,
    tenant_id: str,
    dataset_id: str,
    kind: str,
    limit: int,
    ttl_sec: int = 120,
    retry_defer_sec: int = 2,
):
    """
    Simple per-dataset concurrency limit (Redis counting semaphore).

    Semantics match tenant_acquire(), but the scope is a dataset within a tenant.
    """
    if redis is None or limit <= 0:
        return None

    ds = str(dataset_id or "").strip()
    if not ds:
        return None

    key = f"sem:dataset:{tenant_id}:{ds}:{kind}"
    retry_cls = None
    try:
        retry_cls = get_retry_exc()
    except Exception:  # noqa: BLE001
        retry_cls = None
    try:
        val = await redis.incr(key)
        await redis.expire(key, ttl_sec)
        if int(val) > int(limit):
            await redis.decr(key)
            if retry_cls:
                raise retry_cls(defer=int(retry_defer_sec))
            return None
        return key
    except Exception as exc:  # noqa: BLE001
        if retry_cls is not None:
            try:
                if isinstance(exc, retry_cls):
                    raise
            except TypeError as exc:
                logger.debug("Ignoring non-critical task lock fallback failure: %s", exc)
        logger.warning("Dataset semaphore acquire failed (skip limit): %s", str(exc)[:200])
        return None


async def dataset_release(redis: Any, key: str | None) -> None:
    if redis is None or not key:
        return
    try:
        val = await redis.decr(key)
        if int(val) <= 0:
            await redis.delete(key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Dataset semaphore release failed: %s", str(exc)[:200])


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
