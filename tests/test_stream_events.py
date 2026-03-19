from __future__ import annotations

import asyncio

import pytest

from app.core.stream_events import StreamEmitter, bind_stream_emitter, emit_stream_event, reset_stream_emitter


def test_emit_stream_event_without_emitter_is_noop() -> None:
    emit_stream_event("event", {"message": "x"})


@pytest.mark.asyncio
async def test_stream_emitter_enqueues_and_dedupes() -> None:
    q: asyncio.Queue[dict[str, object] | None] = asyncio.Queue()
    emitter = StreamEmitter(queue=q, loop=asyncio.get_running_loop())
    token = bind_stream_emitter(emitter)
    try:
        emit_stream_event("event", {"message": "hello"}, dedupe_key="k")
        ev = await asyncio.wait_for(q.get(), timeout=1)
        assert isinstance(ev, dict)
        assert ev.get("type") == "event"
        assert isinstance(ev.get("data"), dict)
        assert ev["data"].get("message") == "hello"

        emit_stream_event("event", {"message": "should_not_enqueue"}, dedupe_key="k")
        assert q.empty()
    finally:
        reset_stream_emitter(token)

