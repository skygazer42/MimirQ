import asyncio
import threading

from app.core.async_bridge import run_coroutine_sync


def test_run_coroutine_sync_without_running_loop() -> None:
    calls = 0

    async def work() -> str:
        nonlocal calls
        calls += 1
        return "ok"

    assert run_coroutine_sync(work) == "ok"
    assert calls == 1


def test_run_coroutine_sync_with_running_loop_uses_worker_thread() -> None:
    async def outer() -> tuple[int, int]:
        caller_thread = threading.get_ident()

        async def work() -> int:
            return threading.get_ident()

        return caller_thread, run_coroutine_sync(work)

    caller_thread, worker_thread = asyncio.run(outer())

    assert worker_thread != caller_thread
