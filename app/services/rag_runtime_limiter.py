"""Runtime limiters for blocking RAG work executed from async API routes."""


import asyncio
import contextlib
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager
from typing import Any, TypeVar

from app.core.config import settings
from app.core.database import SessionLocal

T = TypeVar("T")

_gate_lock = threading.Lock()
_gate_limit = 0
_gate: threading.BoundedSemaphore | None = None
_admission_state = threading.local()


def _configured_limit() -> int:
    return max(0, int(getattr(settings, "RAG_RETRIEVAL_OFFLOAD_MAX_CONCURRENCY", 1) or 0))


def _get_gate(limit: int) -> threading.BoundedSemaphore | None:
    global _gate, _gate_limit
    if limit <= 0:
        return None
    with _gate_lock:
        if _gate is None or _gate_limit != limit:
            _gate = threading.BoundedSemaphore(limit)
            _gate_limit = limit
        return _gate


def _release_gate_after_worker(task: asyncio.Task[Any], *, gate: threading.BoundedSemaphore) -> None:
    gate.release()
    if not task.cancelled():
        task.exception()


def _run_admitted(
    func: Callable[..., T],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> T:
    previous_depth = int(getattr(_admission_state, "depth", 0) or 0)
    _admission_state.depth = previous_depth + 1
    try:
        return func(*args, **kwargs)
    finally:
        _admission_state.depth = previous_depth


async def _acquire_gate(gate: threading.BoundedSemaphore) -> None:
    while not gate.acquire(blocking=False):
        await asyncio.sleep(0.01)


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
    gate = _get_gate(limit)
    queued_at = time.perf_counter()
    if gate is None:
        acquired_at = queued_at
        result = await asyncio.to_thread(func, *args, **kwargs)
    else:
        await _acquire_gate(gate)
        acquired_at = time.perf_counter()
        worker_task = asyncio.create_task(
            asyncio.to_thread(_run_admitted, func, args, kwargs)
        )
        worker_task.add_done_callback(lambda task: _release_gate_after_worker(task, gate=gate))
        result = await asyncio.shield(worker_task)
    finished_at = time.perf_counter()

    metrics = {
        "rag_offload_limit": int(limit),
        "rag_offload_queue_ms": round(max(0.0, (acquired_at - queued_at) * 1000.0), 1),
        "rag_offload_exec_ms": round(max(0.0, (finished_at - acquired_at) * 1000.0), 1),
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
    queued_at = time.perf_counter()
    gate = _get_gate(limit)
    already_admitted = bool(getattr(_admission_state, "depth", 0))
    acquired = False
    if gate is not None and not already_admitted:
        effective_cancel_event = cancel_event or getattr(_admission_state, "cancel_event", None)
        if effective_cancel_event is not None and effective_cancel_event.is_set():
            raise RetrievalAdmissionCancelledError("retrieval admission cancelled")
        while not gate.acquire(timeout=0.05):
            if effective_cancel_event is not None and effective_cancel_event.is_set():
                raise RetrievalAdmissionCancelledError("retrieval admission cancelled")
        acquired = True
        if effective_cancel_event is not None and effective_cancel_event.is_set():
            gate.release()
            acquired = False
            raise RetrievalAdmissionCancelledError("retrieval admission cancelled")
    acquired_at = time.perf_counter()
    try:
        result = (
            func(*args, **kwargs)
            if already_admitted or gate is None
            else _run_admitted(func, args, kwargs)
        )
    finally:
        if acquired:
            gate.release()
    finished_at = time.perf_counter()
    if runtime_metrics is not None:
        runtime_metrics.update(
            {
                "rag_offload_limit": int(limit),
                "rag_offload_queue_ms": round(max(0.0, (acquired_at - queued_at) * 1000.0), 1),
                "rag_offload_exec_ms": round(max(0.0, (finished_at - acquired_at) * 1000.0), 1),
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
