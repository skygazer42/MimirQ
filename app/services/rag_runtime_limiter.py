"""Runtime limiters for blocking RAG work executed from async API routes."""


import asyncio
import threading
import time
from collections.abc import Callable
from typing import Any, TypeVar

from app.core.config import settings

T = TypeVar("T")

_gate_lock = threading.Lock()
_gate_limit = 0
_gate: threading.BoundedSemaphore | None = None


def _configured_limit() -> int:
    return max(0, int(getattr(settings, "RAG_RETRIEVAL_OFFLOAD_MAX_CONCURRENCY", 1) or 0))


def _get_gate() -> threading.BoundedSemaphore | None:
    global _gate, _gate_limit
    limit = _configured_limit()
    if limit <= 0:
        return None
    with _gate_lock:
        if _gate is None or _gate_limit != limit:
            _gate = threading.BoundedSemaphore(limit)
            _gate_limit = limit
        return _gate


def _run_with_gate(func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    gate = _get_gate()
    if gate is None:
        return func(*args, **kwargs)
    with gate:
        return func(*args, **kwargs)


def _run_with_gate_timed(
    func: Callable[..., T],
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
) -> tuple[T, dict[str, Any]]:
    limit = _configured_limit()
    gate = _get_gate()
    queued_at = time.perf_counter()
    if gate is None:
        acquired_at = queued_at
        result = func(*args, **kwargs)
        finished_at = time.perf_counter()
    else:
        gate.acquire()
        try:
            acquired_at = time.perf_counter()
            result = func(*args, **kwargs)
            finished_at = time.perf_counter()
        finally:
            gate.release()

    queue_ms = max(0.0, (acquired_at - queued_at) * 1000.0)
    exec_ms = max(0.0, (finished_at - acquired_at) * 1000.0)
    return result, {
        "rag_offload_limit": int(limit),
        "rag_offload_queue_ms": round(queue_ms, 1),
        "rag_offload_exec_ms": round(exec_ms, 1),
    }


async def run_blocking_retrieval_call(
    func: Callable[..., T],
    *args: Any,
    runtime_metrics: dict[str, Any] | None = None,
    **kwargs: Any,
) -> T:
    """Run a blocking retrieval/chat fallback without blocking the event loop.

    The thread gate protects Milvus, embedding, and sync DB paths from being
    oversubscribed by async endpoints.
    """

    result, metrics = await asyncio.to_thread(_run_with_gate_timed, func, args, kwargs)
    if runtime_metrics is not None:
        runtime_metrics.update(metrics)
    return result
