"""
Request-scoped streaming events.

This module provides a lightweight mechanism for deeper service layers to emit
SSE "steps" without threading a queue through every call.

Implementation notes:
- Uses `contextvars` for request scoping (no globals shared across requests).
- Emission is best-effort and never raises to callers.
"""

import asyncio
import contextvars
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class StreamEmitter:
    """
    Emit dict events into an asyncio queue owned by the streaming endpoint.

    `dedupe_keys` is request-scoped and helps avoid spamming repeated progress
    messages when retrieval runs multiple sub-queries.
    """

    queue: asyncio.Queue[dict[str, Any] | None]
    loop: asyncio.AbstractEventLoop
    dedupe_keys: set[str] = field(default_factory=set)

    def emit(self, event: dict[str, Any], *, dedupe_key: str | None = None) -> None:
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None

        if running is self.loop:
            self._enqueue(event, dedupe_key)
            return

        try:
            self.loop.call_soon_threadsafe(self._enqueue, event, dedupe_key)
        except RuntimeError:
            # The streaming loop can close before a worker finishes.
            return

    def _enqueue(self, event: dict[str, Any], dedupe_key: str | None) -> None:
        if dedupe_key and dedupe_key in self.dedupe_keys:
            return
        try:
            self.queue.put_nowait(event)
        except asyncio.QueueFull:
            return
        if dedupe_key:
            self.dedupe_keys.add(dedupe_key)


_stream_emitter: contextvars.ContextVar[StreamEmitter | None] = contextvars.ContextVar(
    "mimirq.stream_emitter",
    default=None,
)


def bind_stream_emitter(emitter: StreamEmitter | None) -> contextvars.Token[StreamEmitter | None]:
    return _stream_emitter.set(emitter)


def reset_stream_emitter(token: contextvars.Token[StreamEmitter | None]) -> None:
    try:
        _stream_emitter.reset(token)
    except (LookupError, ValueError):
        # Best-effort: never fail request processing due to cleanup issues.
        return


def get_stream_emitter() -> StreamEmitter | None:
    return _stream_emitter.get()


def emit_stream_event(
    event_type: str,
    data: dict[str, Any] | None = None,
    *,
    dedupe_key: str | None = None,
) -> None:
    emitter = get_stream_emitter()
    if emitter is None:
        return
    emitter.emit(
        {
            "type": event_type,
            "data": data or {},
        },
        dedupe_key=dedupe_key,
    )


__all__ = [
    "StreamEmitter",
    "bind_stream_emitter",
    "reset_stream_emitter",
    "get_stream_emitter",
    "emit_stream_event",
]
