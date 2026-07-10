
import asyncio


async def yield_control() -> None:
    """Yield once to the current event loop without using asyncio.sleep(0)."""
    loop = asyncio.get_running_loop()
    ready = loop.create_future()
    loop.call_soon(ready.set_result, None)
    await ready
