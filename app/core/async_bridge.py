"""Helpers for invoking async implementations from synchronous APIs."""

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
