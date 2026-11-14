"""Own managed preparation until its committed result can be handed to the queue."""

import asyncio
from collections.abc import Callable
from typing import TypeVar

from sqlalchemy.orm import Session

from app.core.async_bridge import _wait_for_worker_after_cancellation
from app.rag.core.logging import get_logger
from app.services.rag_runtime_limiter import run_blocking_call_with_managed_session

logger = get_logger(__name__)
T = TypeVar("T")


async def prepare_managed_handoff(
    prepare: Callable[[Session], T], *, recover_cancelled: Callable[[Session, T], None]
) -> T:
    worker = asyncio.create_task(run_blocking_call_with_managed_session(prepare, request_db=None))
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        error = await _wait_for_worker_after_cancellation(worker)
        if error is None and not worker.cancelled():
            result = worker.result()
            cleanup = asyncio.create_task(
                run_blocking_call_with_managed_session(lambda db: recover_cancelled(db, result), request_db=None)
            )
            error = await _wait_for_worker_after_cancellation(cleanup)
        if error is not None:
            logger.error(
                "Cancelled preparation could not finish its recovery",
                exc_info=(type(error), error, error.__traceback__),
            )
        raise
