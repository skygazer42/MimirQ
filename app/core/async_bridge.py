"""Helpers for crossing synchronous and asynchronous execution boundaries."""

import asyncio
from collections.abc import Callable, Coroutine
from concurrent.futures import ThreadPoolExecutor
from typing import Any, TypeVar

T = TypeVar("T")


def run_coroutine_sync(factory: Callable[[], Coroutine[Any, Any, T]]) -> T:
    """Run a fresh coroutine, offloading when the caller already owns an event loop."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())

    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(lambda: asyncio.run(factory())).result()


async def _wait_for_worker_after_cancellation(worker_task: asyncio.Task[T]) -> BaseException | None:
    """Consume a worker result while preserving repeated caller cancellation."""
    while True:
        try:
            await asyncio.shield(worker_task)
            return None
        except asyncio.CancelledError:
            if worker_task.done():
                if worker_task.cancelled():
                    return None
                return worker_task.exception()
            continue
        except BaseException as exc:  # noqa: BLE001 - worker failures must be consumed before cancellation propagates
            return exc


async def run_blocking_in_thread(
    func: Callable[..., T],
    *args: Any,
    on_cancelled_worker_error: Callable[[BaseException], None] | None = None,
    **kwargs: Any,
) -> T:
    """Run blocking work off-loop without abandoning it when the caller is cancelled."""
    worker_task = asyncio.create_task(asyncio.to_thread(func, *args, **kwargs))
    try:
        return await asyncio.shield(worker_task)
    except asyncio.CancelledError:
        worker_error = await _wait_for_worker_after_cancellation(worker_task)
        if worker_error is not None and on_cancelled_worker_error is not None:
            on_cancelled_worker_error(worker_error)
        raise


async def run_coroutine_in_thread(
    factory: Callable[[], Coroutine[Any, Any, T]],
    *,
    on_cancelled_worker_error: Callable[[BaseException], None] | None = None,
) -> T:
    """Run an async implementation in a private event loop on a worker thread."""

    def run() -> T:
        return asyncio.run(factory())

    return await run_blocking_in_thread(
        run,
        on_cancelled_worker_error=on_cancelled_worker_error,
    )
