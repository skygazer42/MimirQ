import asyncio
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from app.core.config import settings
from app.core.optional_deps import require_dependency
from app.rag.core.logging import get_logger

if TYPE_CHECKING:
    from arq import Retry

logger = get_logger("tasks.locks")

_COMPARE_DELETE_LUA = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
  return redis.call("DEL", KEYS[1])
end
return 0
"""

_COMPARE_EXPIRE_LUA = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
  return redis.call("EXPIRE", KEYS[1], ARGV[2])
end
return 0
"""

_SEMAPHORE_LEASE_SEPARATOR = "|"
_SEMAPHORE_BUSY_ATTR = "_mimirq_semaphore_busy"
_TASK_JOB_LOCK_MIN_TTL_SEC = 40 * 60
_TASK_SEMAPHORE_LEASE_MIN_TTL_SEC = 5
_TASK_SEMAPHORE_HEARTBEAT_MAX_INTERVAL_SEC = 10.0
_TASK_SEMAPHORE_WAIT_POLL_INTERVAL_SEC = 0.1


@dataclass(slots=True)
class _SemaphoreHeartbeat:
    stop_event: asyncio.Event
    task: asyncio.Task[None]


_SEMAPHORE_HEARTBEATS: dict[str, _SemaphoreHeartbeat] = {}
_SEMAPHORE_HEARTBEATS_LOCK = threading.Lock()


def task_job_lock_ttl_sec(*, minimum_sec: int = _TASK_JOB_LOCK_MIN_TTL_SEC) -> int:
    return max(minimum_sec, settings.TASK_JOB_TIMEOUT_SEC + 60)


def task_semaphore_lease_ttl_sec(
    *,
    minimum_sec: int = _TASK_SEMAPHORE_LEASE_MIN_TTL_SEC,
) -> int:
    return max(minimum_sec, settings.TASK_SEMAPHORE_LEASE_TTL_SEC)


def get_retry_exc() -> "type[Retry]":
    # When task queue is enabled, Retry must exist; failing silently would bypass concurrency limits.
    mod = require_dependency("arq", feature="task_queue_retry")
    return mod.Retry


def _semaphore_busy_retry(retry_cls: "type[Retry]", *, defer_sec: int) -> "Retry":
    exc = retry_cls(defer=defer_sec)
    setattr(exc, _SEMAPHORE_BUSY_ATTR, True)
    return exc


def is_semaphore_busy_retry(exc: Exception) -> bool:
    return bool(getattr(exc, _SEMAPHORE_BUSY_ATTR, False))


async def _eval_redis_script(redis: Any, script: str, *, keys: tuple[str, ...], args: tuple[Any, ...]) -> Any:
    return await redis.eval(script, len(keys), *keys, *args)


async def _semaphore_acquire(
    redis: Any,
    *,
    key_prefix: str,
    limit: int,
    ttl_sec: int,
    wait_timeout_sec: float = 0.0,
) -> str | None:
    token = uuid4().hex
    loop = asyncio.get_running_loop()
    deadline = loop.time() + max(0.0, wait_timeout_sec)
    while True:
        for slot in range(1, limit + 1):
            key = f"{key_prefix}:{slot}"
            if await redis.set(key, token, ex=max(1, ttl_sec), nx=True):
                return f"{key}{_SEMAPHORE_LEASE_SEPARATOR}{token}"
        remaining_sec = deadline - loop.time()
        if remaining_sec <= 0:
            return None
        await asyncio.sleep(min(_TASK_SEMAPHORE_WAIT_POLL_INTERVAL_SEC, remaining_sec))


def _semaphore_heartbeat_interval_sec(ttl_sec: int) -> float:
    return max(1.0, min(ttl_sec / 3.0, _TASK_SEMAPHORE_HEARTBEAT_MAX_INTERVAL_SEC))


async def _semaphore_refresh(redis: Any, *, key: str, token: str, ttl_sec: int) -> bool | None:
    try:
        refreshed = await _eval_redis_script(
            redis,
            _COMPARE_EXPIRE_LUA,
            keys=(key,),
            args=(token, max(1, ttl_sec)),
        )
        return bool(refreshed)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Semaphore heartbeat refresh failed: %s", str(exc)[:200])
        # A transient Redis failure is not proof that ownership was lost. Keep
        # retrying until Redis can atomically confirm or reject the token.
        return None


async def _run_semaphore_heartbeat(
    redis: Any, *, lease: str, key: str, token: str, ttl_sec: int, stop_event: asyncio.Event
) -> None:
    interval_sec = _semaphore_heartbeat_interval_sec(ttl_sec)
    try:
        while True:
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval_sec)
                break
            except TimeoutError:
                refreshed = await _semaphore_refresh(redis, key=key, token=token, ttl_sec=ttl_sec)
                if refreshed is False:
                    logger.warning("Semaphore lease heartbeat stopped after ownership loss: %s", key)
                    break
    except asyncio.CancelledError:
        raise
    finally:
        with _SEMAPHORE_HEARTBEATS_LOCK:
            controller = _SEMAPHORE_HEARTBEATS.get(lease)
            if controller is not None and controller.stop_event is stop_event:
                _SEMAPHORE_HEARTBEATS.pop(lease, None)


def _register_semaphore_heartbeat(redis: Any, *, lease: str, key: str, token: str, ttl_sec: int) -> None:
    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()
    task = loop.create_task(
        _run_semaphore_heartbeat(redis, lease=lease, key=key, token=token, ttl_sec=ttl_sec, stop_event=stop_event)
    )
    controller = _SemaphoreHeartbeat(stop_event=stop_event, task=task)
    with _SEMAPHORE_HEARTBEATS_LOCK:
        previous = _SEMAPHORE_HEARTBEATS.get(lease)
        _SEMAPHORE_HEARTBEATS[lease] = controller
    if previous is not None:
        previous.stop_event.set()
        previous.task.cancel()


async def _semaphore_release(redis: Any, lease: str) -> None:
    try:
        key, token = lease.rsplit(_SEMAPHORE_LEASE_SEPARATOR, 1)
    except ValueError:
        logger.warning("Ignoring malformed semaphore lease")
        return
    with _SEMAPHORE_HEARTBEATS_LOCK:
        controller = _SEMAPHORE_HEARTBEATS.pop(lease, None)
    try:
        if controller is not None:
            controller.stop_event.set()
            controller.task.cancel()
            await asyncio.wait({controller.task})
            if not controller.task.cancelled():
                controller.task.result()
    finally:
        if key and token:
            await release_lock(redis, key=key, value=token)


async def _acquire_semaphore_lease(
    redis: Any,
    *,
    scope: str,
    key_prefix: str,
    limit: int,
    ttl_sec: int,
    retry_defer_sec: int,
    wait_timeout_sec: float,
) -> str:
    retry_cls = get_retry_exc()
    if redis is None:
        logger.warning(f"{scope} semaphore acquire failed (retry): Redis client unavailable")
        raise retry_cls(defer=retry_defer_sec)
    try:
        lease = await _semaphore_acquire(
            redis,
            key_prefix=key_prefix,
            limit=limit,
            ttl_sec=ttl_sec,
            wait_timeout_sec=wait_timeout_sec,
        )
        if lease is None:
            raise _semaphore_busy_retry(retry_cls, defer_sec=retry_defer_sec)
        key, token = lease.rsplit(_SEMAPHORE_LEASE_SEPARATOR, 1)
        _register_semaphore_heartbeat(redis, lease=lease, key=key, token=token, ttl_sec=ttl_sec)
        return lease
    except Exception as exc:  # noqa: BLE001
        if isinstance(exc, retry_cls):
            raise
        logger.warning(f"{scope} semaphore acquire failed (retry): %s", str(exc)[:200])
        raise retry_cls(defer=retry_defer_sec) from exc


async def tenant_acquire(
    redis: Any,
    *,
    tenant_id: str,
    kind: str,
    limit: int,
    ttl_sec: int = 120,
    retry_defer_sec: int = 2,
    wait_timeout_sec: float = 0.0,
) -> str | None:
    """
    Per-tenant concurrency limit backed by expiring, owner-scoped Redis slots.

    Returns an opaque lease string on success, else None.
    """
    if limit <= 0:
        return None

    key_prefix = f"sem:tenant:{tenant_id}:{kind}"
    return await _acquire_semaphore_lease(
        redis,
        scope="Tenant",
        key_prefix=key_prefix,
        limit=limit,
        ttl_sec=ttl_sec,
        retry_defer_sec=retry_defer_sec,
        wait_timeout_sec=wait_timeout_sec,
    )


async def dataset_acquire(
    redis: Any,
    *,
    tenant_id: str,
    dataset_id: str,
    kind: str,
    limit: int,
    ttl_sec: int = 120,
    retry_defer_sec: int = 2,
    wait_timeout_sec: float = 0.0,
) -> str | None:
    """
    Per-dataset concurrency limit backed by expiring, owner-scoped Redis slots.

    Semantics match tenant_acquire(), but the scope is a dataset within a tenant.
    """
    if limit <= 0:
        return None

    ds = dataset_id.strip()
    if not ds:
        return None

    key_prefix = f"sem:dataset:{tenant_id}:{ds}:{kind}"
    return await _acquire_semaphore_lease(
        redis,
        scope="Dataset",
        key_prefix=key_prefix,
        limit=limit,
        ttl_sec=ttl_sec,
        retry_defer_sec=retry_defer_sec,
        wait_timeout_sec=wait_timeout_sec,
    )


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
            raise retry_cls(defer=retry_defer_sec)
        if fail_open:
            return True
        raise RuntimeError("Redis client unavailable")
    try:
        acquired = await redis.set(key, value, ex=ttl_sec, nx=True)
        return bool(acquired)
    except Exception as exc:  # noqa: BLE001
        if retry_defer_sec is not None:
            retry_cls = get_retry_exc()
            logger.warning("Redis lock acquire failed (retry): %s", str(exc)[:200])
            raise retry_cls(defer=retry_defer_sec) from exc
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
        await _eval_redis_script(redis, _COMPARE_DELETE_LUA, keys=(key,), args=(value,))
    except Exception as exc:  # noqa: BLE001
        logger.warning("Redis lock release failed: %s", str(exc)[:200])


def make_lock_value(requested_by: str) -> str:
    return f"{requested_by}:{uuid4().hex}"
