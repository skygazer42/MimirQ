"""Runtime limiters for blocking RAG work executed from async API routes."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from typing import Any, TypeVar

from app.core.config import settings

T = TypeVar("T")

_gate_lock = threading.Lock()
_gate_limit = 0
_gate: threading.BoundedSemaphore | None = None


def _configured_limit() -> int:
    return max(0, int(getattr(settings, "RAG_RETRIEVAL_OFFLOAD_MAX_CONCURRENCY", 2) or 0))


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


async def run_blocking_retrieval_call(func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Run a blocking retrieval/chat fallback without blocking the event loop.

    The thread gate protects Milvus, embedding, and sync DB paths from being
    oversubscribed by async endpoints.
    """

    return await asyncio.to_thread(_run_with_gate, func, *args, **kwargs)
