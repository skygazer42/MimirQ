"""Runtime limiters for blocking RAG work executed from async API routes."""


import asyncio
import contextlib
import logging
import math
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, TypeVar
from uuid import uuid4

from fastapi import HTTPException

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.redis_client import LazyRedisClient
from app.core.redis_lease import extend_redis_lease, release_redis_lease, try_acquire_redis_lease

T = TypeVar("T")
logger = logging.getLogger(__name__)

_gate_lock = threading.Lock()
_gate_limit = 0
_gate: threading.BoundedSemaphore | None = None
_admission_state = threading.local()
_distributed_admission_lease_heartbeats: dict[
    tuple[str, str],
    tuple[threading.Event, threading.Thread],
] = {}
_distributed_admission_heartbeat_lock = threading.Lock()
_redis_client_slot = LazyRedisClient(
    url=lambda: settings.REDIS_URL,
    kwargs={
        "socket_timeout": 1,
        "socket_connect_timeout": 1,
        "decode_responses": False,
    },
    skip_empty_url=True,
    strip_url=True,
)
_get_redis_client = _redis_client_slot.get
_invalidate_redis_client = _redis_client_slot.invalidate


@dataclass(frozen=True)
class _DistributedAdmissionLease:
    key: str
    owner: str


def _configured_limit() -> int:
    return max(0, int(getattr(settings, "RAG_RETRIEVAL_OFFLOAD_MAX_CONCURRENCY", 1) or 0))


def _configured_admission_timeout_sec() -> float:
    return max(0.0, float(getattr(settings, "RAG_RETRIEVAL_ADMISSION_TIMEOUT_SEC", 15.0) or 0.0))


def _configured_distributed_limit(limit: int) -> int:
    configured = int(getattr(settings, "RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_MAX_CONCURRENCY", limit) or 0)
    return max(0, limit if configured <= 0 else configured)


def _distributed_admission_enabled(limit: int) -> bool:
    return bool(getattr(settings, "RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_ENABLED", False)) and (
        _configured_distributed_limit(limit) > 0
    )


def _distributed_admission_prefix() -> str:
    return (
        str(getattr(settings, "RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_PREFIX", "ragadm") or "ragadm").strip()
        or "ragadm"
    )


def _distributed_admission_ttl_sec(timeout_sec: float) -> int:
    return max(60, min(300, max(int(math.ceil(timeout_sec or 0.0)) + 30, 60)))


def _current_distributed_admission_depth() -> int:
    return int(getattr(_admission_state, "distributed_depth", 0) or 0)


def _current_distributed_admission_lease() -> _DistributedAdmissionLease | None:
    lease = getattr(_admission_state, "distributed_lease", None)
    return lease if isinstance(lease, _DistributedAdmissionLease) else None


def _try_acquire_distributed_admission_slot(
    *,
    limit: int,
    timeout_sec: float,
) -> tuple[_DistributedAdmissionLease | None, bool]:
    if not _distributed_admission_enabled(limit) or _current_distributed_admission_depth() > 0:
        return None, False
    client = _get_redis_client()
    if client is None:
        return None, True
    owner = uuid4().hex
    ttl_sec = _distributed_admission_ttl_sec(timeout_sec)
    prefix = _distributed_admission_prefix()
    distributed_limit = _configured_distributed_limit(limit)
    for slot in range(1, distributed_limit + 1):
        key = f"{prefix}:{slot}"
        try:
            if try_acquire_redis_lease(client, key, value=owner, ttl_sec=ttl_sec):
                return _DistributedAdmissionLease(key=key, owner=owner), False
        except Exception as exc:  # noqa: BLE001
            logger.warning("Distributed retrieval admission degraded to local gate: %s", str(exc)[:200])
            _invalidate_redis_client()
            return None, True
    return None, False


def _release_distributed_admission_slot(lease: _DistributedAdmissionLease | None) -> None:
    if lease is None:
        return
    client = _get_redis_client()
    if client is None:
        return
    try:
        release_redis_lease(client, lease.key, value=lease.owner)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Distributed retrieval admission release failed: %s", str(exc)[:200])
        _invalidate_redis_client()


def _distributed_admission_lease_renew_interval_sec(ttl_sec: int) -> float:
    return max(1.0, min(float(ttl_sec) / 3.0, 30.0))


def _stop_distributed_admission_lease_heartbeat(lease: _DistributedAdmissionLease | None) -> None:
    if lease is None:
        return
    with _distributed_admission_heartbeat_lock:
        heartbeat = _distributed_admission_lease_heartbeats.pop((lease.key, lease.owner), None)
    if heartbeat is None:
        return
    stop_event, thread = heartbeat
    stop_event.set()
    thread.join(timeout=0.25)


def _start_distributed_admission_lease_heartbeat(
    lease: _DistributedAdmissionLease | None,
    *,
    ttl_sec: int,
) -> None:
    if lease is None:
        return
    stop_event = threading.Event()
    renew_interval_sec = _distributed_admission_lease_renew_interval_sec(ttl_sec)

    def _maintain() -> None:
        while not stop_event.wait(renew_interval_sec):
            client = _get_redis_client()
            if client is None:
                return
            try:
                renewed = extend_redis_lease(
                    client,
                    lease.key,
                    value=lease.owner,
                    ttl_sec=ttl_sec,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Distributed retrieval admission extend failed: %s", str(exc)[:200])
                _invalidate_redis_client()
                return
            if not renewed:
                return

    thread = threading.Thread(
        target=_maintain,
        name="retrieval-admission-lease-heartbeat",
        daemon=True,
    )
    with _distributed_admission_heartbeat_lock:
        _distributed_admission_lease_heartbeats[(lease.key, lease.owner)] = (stop_event, thread)
    thread.start()


@contextmanager
def _distributed_admission_scope(lease: _DistributedAdmissionLease | None):
    if lease is None:
        yield
        return
    previous_depth = _current_distributed_admission_depth()
    previous_lease = _current_distributed_admission_lease()
    _admission_state.distributed_depth = previous_depth + 1
    _admission_state.distributed_lease = lease
    try:
        yield
    finally:
        _admission_state.distributed_depth = previous_depth
        if previous_lease is None:
            if hasattr(_admission_state, "distributed_lease"):
                delattr(_admission_state, "distributed_lease")
        else:
            _admission_state.distributed_lease = previous_lease


def _get_gate(limit: int) -> threading.BoundedSemaphore | None:
    global _gate, _gate_limit
    if limit <= 0:
        return None
    with _gate_lock:
        if _gate is None or _gate_limit != limit:
            _gate = threading.BoundedSemaphore(limit)
            _gate_limit = limit
        return _gate


def _release_gate_after_worker(
    task: asyncio.Task[Any],
    *,
    gate: threading.BoundedSemaphore | None = None,
    distributed_lease: _DistributedAdmissionLease | None = None,
) -> None:
    if gate is not None:
        gate.release()
    _stop_distributed_admission_lease_heartbeat(distributed_lease)
    _release_distributed_admission_slot(distributed_lease)
    if not task.cancelled():
        task.exception()


def _run_admitted(
    func: Callable[..., T],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    *,
    distributed_lease: _DistributedAdmissionLease | None = None,
) -> T:
    previous_depth = int(getattr(_admission_state, "depth", 0) or 0)
    _admission_state.depth = previous_depth + 1
    try:
        with _distributed_admission_scope(distributed_lease):
            return func(*args, **kwargs)
    finally:
        _admission_state.depth = previous_depth


class RetrievalAdmissionTimeoutError(HTTPException):
    """Retrieval capacity stayed full past the configured queue deadline."""

    def __init__(self, timeout_sec: float):
        retry_after_sec = max(1, math.ceil(timeout_sec))
        super().__init__(
            status_code=503,
            detail="Retrieval capacity is busy. Retry later.",
            headers={"Retry-After": str(retry_after_sec)},
        )


def _admission_deadline(timeout_sec: float) -> float | None:
    return time.perf_counter() + timeout_sec if timeout_sec > 0.0 else None


def _remaining_admission_time(
    *,
    deadline: float | None,
    timeout_sec: float,
) -> float | None:
    if deadline is None:
        return None
    remaining = deadline - time.perf_counter()
    if remaining <= 0.0:
        raise RetrievalAdmissionTimeoutError(timeout_sec)
    return remaining


async def _acquire_gate(
    gate: threading.BoundedSemaphore,
    *,
    deadline: float | None,
    timeout_sec: float,
) -> None:
    while True:
        remaining = _remaining_admission_time(
            deadline=deadline,
            timeout_sec=timeout_sec,
        )
        if gate.acquire(blocking=False):
            return
        await asyncio.sleep(min(0.01, remaining) if deadline is not None else 0.01)


@contextmanager
def retrieval_cancellation_scope(cancel_event: threading.Event):
    previous = getattr(_admission_state, "cancel_event", None)
    _admission_state.cancel_event = cancel_event
    try:
        yield
    finally:
        _admission_state.cancel_event = previous


class RetrievalAdmissionCancelledError(RuntimeError):
    """Queued synchronous retrieval was abandoned before it acquired capacity."""


def _run_with_managed_session(
    func: Callable[..., T],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> T:
    worker_db = SessionLocal()
    try:
        return func(worker_db, *args, **kwargs)
    finally:
        worker_db.close()


def _release_request_session(request_db: Any | None) -> None:
    rollback = getattr(request_db, "rollback", None)
    if callable(rollback):
        with contextlib.suppress(Exception):
            rollback()


async def run_blocking_retrieval_call(
    func: Callable[..., T],
    *args: Any,
    runtime_metrics: dict[str, Any] | None = None,
    **kwargs: Any,
) -> T:
    """Run a blocking retrieval/chat fallback without blocking the event loop.

    The admission gate protects Milvus, embedding, and sync DB paths from being
    oversubscribed by async endpoints.
    """

    limit = _configured_limit()
    admission_timeout_sec = _configured_admission_timeout_sec()
    distributed_ttl_sec = _distributed_admission_ttl_sec(admission_timeout_sec)
    gate = _get_gate(limit)
    queued_at = time.perf_counter()
    wait_deadline = _admission_deadline(admission_timeout_sec)
    distributed_lease = None
    distributed_state = "disabled"
    gate_acquired = False
    try:
        while True:
            if gate is not None and not gate_acquired:
                await _acquire_gate(
                    gate,
                    deadline=wait_deadline,
                    timeout_sec=admission_timeout_sec,
                )
                gate_acquired = True
            distributed_lease, degraded = await asyncio.to_thread(
                _try_acquire_distributed_admission_slot,
                limit=limit,
                timeout_sec=admission_timeout_sec,
            )
            if distributed_lease is not None:
                distributed_state = "acquired"
                _start_distributed_admission_lease_heartbeat(
                    distributed_lease,
                    ttl_sec=distributed_ttl_sec,
                )
                break
            if not _distributed_admission_enabled(limit):
                distributed_state = "disabled"
                break
            if degraded:
                distributed_state = "degraded_local_only"
                break
            if gate_acquired and gate is not None:
                gate.release()
                gate_acquired = False
            remaining = _remaining_admission_time(
                deadline=wait_deadline,
                timeout_sec=admission_timeout_sec,
            )
            await asyncio.sleep(min(0.01, remaining) if remaining is not None else 0.01)
        acquired_at = time.perf_counter()
        worker_task = asyncio.create_task(
            asyncio.to_thread(_run_admitted, func, args, kwargs, distributed_lease=distributed_lease)
        )
        worker_task.add_done_callback(
            lambda task: _release_gate_after_worker(task, gate=gate, distributed_lease=distributed_lease)
        )
    except BaseException:
        if gate_acquired and gate is not None:
            gate.release()
        _stop_distributed_admission_lease_heartbeat(distributed_lease)
        _release_distributed_admission_slot(distributed_lease)
        raise
    result = await asyncio.shield(worker_task)
    finished_at = time.perf_counter()

    metrics = {
        "rag_offload_limit": int(limit),
        "rag_offload_queue_ms": round(max(0.0, (acquired_at - queued_at) * 1000.0), 1),
        "rag_offload_exec_ms": round(max(0.0, (finished_at - acquired_at) * 1000.0), 1),
        "rag_distributed_admission_enabled": bool(_distributed_admission_enabled(limit)),
        "rag_distributed_admission_active": distributed_lease is not None,
        "rag_distributed_admission_limit": int(_configured_distributed_limit(limit)),
        "rag_distributed_admission_state": distributed_state,
        "rag_offload_global_budget": int(_configured_distributed_limit(limit)),
    }
    if runtime_metrics is not None:
        runtime_metrics.update(metrics)
    return result


def run_blocking_retrieval_call_sync(
    func: Callable[..., T],
    *args: Any,
    runtime_metrics: dict[str, Any] | None = None,
    cancel_event: threading.Event | None = None,
    **kwargs: Any,
) -> T:
    """Run retrieval from an existing worker while sharing process admission."""

    limit = _configured_limit()
    admission_timeout_sec = _configured_admission_timeout_sec()
    distributed_ttl_sec = _distributed_admission_ttl_sec(admission_timeout_sec)
    queued_at = time.perf_counter()
    gate = _get_gate(limit)
    already_admitted = bool(getattr(_admission_state, "depth", 0))
    already_distributed_admitted = _current_distributed_admission_depth() > 0
    acquired = False
    distributed_lease = None
    distributed_state = "nested" if already_distributed_admitted else "disabled"
    wait_deadline = _admission_deadline(admission_timeout_sec)
    effective_cancel_event = cancel_event or getattr(_admission_state, "cancel_event", None)
    try:
        while True:
            if gate is not None and not already_admitted and not acquired:
                while True:
                    if effective_cancel_event is not None and effective_cancel_event.is_set():
                        raise RetrievalAdmissionCancelledError("retrieval admission cancelled")
                    remaining = _remaining_admission_time(
                        deadline=wait_deadline,
                        timeout_sec=admission_timeout_sec,
                    )
                    wait_sec = min(0.05, remaining) if remaining is not None else 0.05
                    if gate.acquire(timeout=wait_sec):
                        break
                acquired = True
                if effective_cancel_event is not None and effective_cancel_event.is_set():
                    raise RetrievalAdmissionCancelledError("retrieval admission cancelled")
            if already_distributed_admitted:
                break
            distributed_lease, degraded = _try_acquire_distributed_admission_slot(
                limit=limit,
                timeout_sec=admission_timeout_sec,
            )
            if distributed_lease is not None:
                distributed_state = "acquired"
                _start_distributed_admission_lease_heartbeat(
                    distributed_lease,
                    ttl_sec=distributed_ttl_sec,
                )
                break
            if not _distributed_admission_enabled(limit):
                distributed_state = "disabled"
                break
            if degraded:
                distributed_state = "degraded_local_only"
                break
            if acquired and gate is not None:
                gate.release()
                acquired = False
            remaining = _remaining_admission_time(
                deadline=wait_deadline,
                timeout_sec=admission_timeout_sec,
            )
            time.sleep(min(0.01, remaining) if remaining is not None else 0.01)
        acquired_at = time.perf_counter()
        with _distributed_admission_scope(distributed_lease):
            result = (
                func(*args, **kwargs)
                if already_admitted or gate is None
                else _run_admitted(func, args, kwargs)
            )
    finally:
        if acquired:
            gate.release()
        _stop_distributed_admission_lease_heartbeat(distributed_lease)
        _release_distributed_admission_slot(distributed_lease)
    finished_at = time.perf_counter()
    if runtime_metrics is not None:
        runtime_metrics.update(
            {
                "rag_offload_limit": int(limit),
                "rag_offload_queue_ms": round(max(0.0, (acquired_at - queued_at) * 1000.0), 1),
                "rag_offload_exec_ms": round(max(0.0, (finished_at - acquired_at) * 1000.0), 1),
                "rag_distributed_admission_enabled": bool(_distributed_admission_enabled(limit)),
                "rag_distributed_admission_active": distributed_lease is not None or already_distributed_admitted,
                "rag_distributed_admission_limit": int(_configured_distributed_limit(limit)),
                "rag_distributed_admission_state": distributed_state,
                "rag_offload_global_budget": int(_configured_distributed_limit(limit)),
            }
        )
    return result


async def run_blocking_retrieval_call_with_managed_session(
    func: Callable[..., T],
    *args: Any,
    request_db: Any | None,
    runtime_metrics: dict[str, Any] | None = None,
    **kwargs: Any,
) -> T:
    """Offload blocking work while keeping SQLAlchemy sessions thread-owned."""

    _release_request_session(request_db)
    return await run_blocking_retrieval_call(
        _run_with_managed_session,
        func,
        args,
        kwargs,
        runtime_metrics=runtime_metrics,
    )


async def run_blocking_call_with_managed_session(
    func: Callable[..., T],
    *args: Any,
    request_db: Any | None,
    **kwargs: Any,
) -> T:
    """Offload non-retrieval work with a thread-owned database session."""

    _release_request_session(request_db)
    return await asyncio.to_thread(
        _run_with_managed_session,
        func,
        args,
        kwargs,
    )
