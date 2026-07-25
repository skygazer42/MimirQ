
from typing import Any
from uuid import uuid4

from app.core.optional_deps import require_dependency
from app.rag.core.logging import get_logger

logger = get_logger("tasks.locks")

_SCRIPT_UNAVAILABLE = object()

_COMPARE_DELETE_LUA = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
  return redis.call("DEL", KEYS[1])
end
return 0
"""

_SEMAPHORE_LEASE_SEPARATOR = "|"
_SEMAPHORE_BUSY_ATTR = "_mimirq_semaphore_busy"


def get_retry_exc():  # noqa: ANN201
    # When task queue is enabled, Retry must exist; failing silently would bypass concurrency limits.
    mod = require_dependency("arq", feature="task_queue_retry")
    retry_cls = getattr(mod, "Retry", None)
    if retry_cls is None:
        # If arq is installed but doesn't expose Retry, it's likely a version mismatch.
        raise RuntimeError("arq is installed but Retry is missing (version mismatch?)")
    return retry_cls


def _semaphore_busy_retry(retry_cls, *, defer_sec: int) -> Exception:  # noqa: ANN001
    exc = retry_cls(defer=int(defer_sec))
    setattr(exc, _SEMAPHORE_BUSY_ATTR, True)
    return exc


def is_semaphore_busy_retry(exc: Exception) -> bool:
    return bool(getattr(exc, _SEMAPHORE_BUSY_ATTR, False))


async def _eval_redis_script(redis: Any, script: str, *, keys: tuple[str, ...], args: tuple[Any, ...]) -> Any:
    eval_fn = getattr(redis, "eval", None)
    if callable(eval_fn):
        return await eval_fn(script, len(keys), *keys, *args)

    execute_command = getattr(redis, "execute_command", None)
    if callable(execute_command):
        return await execute_command("EVAL", script, len(keys), *keys, *args)

    return _SCRIPT_UNAVAILABLE


async def _semaphore_acquire(
    redis: Any,
    *,
    key_prefix: str,
    limit: int,
    ttl_sec: int,
) -> str | None:
    token = uuid4().hex
    for slot in range(1, int(limit) + 1):
        key = f"{key_prefix}:{slot}"
        if await redis.set(key, token, ex=max(1, int(ttl_sec)), nx=True):
            return f"{key}{_SEMAPHORE_LEASE_SEPARATOR}{token}"
    return None


async def _semaphore_release(redis: Any, lease: str) -> None:
    try:
        key, token = lease.rsplit(_SEMAPHORE_LEASE_SEPARATOR, 1)
    except ValueError:
        logger.warning("Ignoring malformed semaphore lease")
        return
    if key and token:
        await release_lock(redis, key=key, value=token)


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
    Per-tenant concurrency limit backed by expiring, owner-scoped Redis slots.

    Returns an opaque lease string on success, else None.
    """
    if limit <= 0:
        return None

    key_prefix = f"sem:tenant:{tenant_id}:{kind}"
    retry_cls = get_retry_exc()
    if redis is None:
        logger.warning("Tenant semaphore acquire failed (retry): Redis client unavailable")
        raise retry_cls(defer=int(retry_defer_sec))
    try:
        lease = await _semaphore_acquire(redis, key_prefix=key_prefix, limit=limit, ttl_sec=ttl_sec)
        if lease is None:
            raise _semaphore_busy_retry(retry_cls, defer_sec=retry_defer_sec)
        return lease
    except Exception as exc:  # noqa: BLE001
        if isinstance(exc, retry_cls):
            raise
        logger.warning("Tenant semaphore acquire failed (retry): %s", str(exc)[:200])
        raise retry_cls(defer=int(retry_defer_sec)) from exc


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
    Per-dataset concurrency limit backed by expiring, owner-scoped Redis slots.

    Semantics match tenant_acquire(), but the scope is a dataset within a tenant.
    """
    if limit <= 0:
        return None

    ds = str(dataset_id or "").strip()
    if not ds:
        return None

    key_prefix = f"sem:dataset:{tenant_id}:{ds}:{kind}"
    retry_cls = get_retry_exc()
    if redis is None:
        logger.warning("Dataset semaphore acquire failed (retry): Redis client unavailable")
        raise retry_cls(defer=int(retry_defer_sec))
    try:
        lease = await _semaphore_acquire(redis, key_prefix=key_prefix, limit=limit, ttl_sec=ttl_sec)
        if lease is None:
            raise _semaphore_busy_retry(retry_cls, defer_sec=retry_defer_sec)
        return lease
    except Exception as exc:  # noqa: BLE001
        if isinstance(exc, retry_cls):
            raise
        logger.warning("Dataset semaphore acquire failed (retry): %s", str(exc)[:200])
        raise retry_cls(defer=int(retry_defer_sec)) from exc


async def dataset_release(redis: Any, key: str | None) -> None:
    if redis is None or not key:
        return
    try:
        await _semaphore_release(redis, key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Dataset semaphore release failed: %s", str(exc)[:200])


async def tenant_release(redis: Any, key: str | None) -> None:
    if redis is None or not key:
        return
    try:
        await _semaphore_release(redis, key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Tenant semaphore release failed: %s", str(exc)[:200])


async def acquire_lock(
    redis: Any,
    *,
    key: str,
    value: str,
    ttl_sec: int,
    fail_open: bool = True,
    retry_defer_sec: int | None = None,
) -> bool:
    """
    Best-effort idempotency lock (Redis SET NX EX).

    Returns:
        True if lock acquired (or Redis unavailable / fail-open fallback)
        False if lock already held
    """
    if redis is None:
        if retry_defer_sec is not None:
            retry_cls = get_retry_exc()
            logger.warning("Redis lock acquire failed (retry): Redis client unavailable")
            raise retry_cls(defer=int(retry_defer_sec))
        if fail_open:
            return True
        raise RuntimeError("Redis client unavailable")
    try:
        acquired = await redis.set(key, value, ex=int(ttl_sec), nx=True)
        return bool(acquired)
    except Exception as exc:  # noqa: BLE001
        if retry_defer_sec is not None:
            retry_cls = get_retry_exc()
            logger.warning("Redis lock acquire failed (retry): %s", str(exc)[:200])
            raise retry_cls(defer=int(retry_defer_sec)) from exc
        if fail_open:
            logger.warning("Redis lock acquire failed (continue without lock): %s", str(exc)[:200])
            return True
        logger.warning("Redis lock acquire failed (fail closed): %s", str(exc)[:200])
        raise


async def release_lock(redis: Any, *, key: str, value: str) -> None:
    """
    Best-effort idempotency lock release.

    Only deletes the key when the stored value matches `value`.
    """
    if redis is None:
        return
    try:
        deleted = await _eval_redis_script(redis, _COMPARE_DELETE_LUA, keys=(key,), args=(value,))
        if deleted is _SCRIPT_UNAVAILABLE:
            cur = await redis.get(key)
            cur_decoded = cur.decode("utf-8", "ignore") if isinstance(cur, (bytes, bytearray)) else cur
            if cur_decoded == value:
                await redis.delete(key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis lock release failed: %s", str(exc)[:200])


def make_lock_value(requested_by: str) -> str:
    return f"{requested_by}:{uuid4().hex}"
