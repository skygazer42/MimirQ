"""
Arq worker configuration entry.

Start method (container/local):
  arq app.tasks.worker.WorkerSettings
"""

import asyncio
import contextlib
import os
import socket
from collections.abc import Awaitable, Callable
from typing import Any

from arq.connections import RedisSettings
from arq.worker import func

from app.core.config import settings
from app.rag.core.logging import get_logger
from app.tasks.jobs import (
    connector_run_job,
    dataset_precheck_scan_job,
    dataset_profile_scan_job,
    evidence_reference_sources_repair_job,
    extract_kg_job,
    ping_job,
    process_document_job,
    rebuild_indexes_job,
)

logger = get_logger("tasks.worker")

_SOCKET_CONNECT_PROBE_TIMEOUT_SEC = 0.2
_WORKER_HEARTBEAT_TASK_KEY = "_mimirq_worker_heartbeat_task"


def _warn_if_redis_unreachable(redis_settings: RedisSettings) -> None:
    """
    Best-effort: emit a clear log line if Redis isn't reachable at worker startup.

    This runs at import-time (before arq configures logging) so we intentionally
    log at WARNING level to ensure it is visible via Python's last-resort handler.
    """

    if not isinstance(redis_settings.host, str):
        return

    host = redis_settings.host
    port = int(redis_settings.port)
    try:
        with socket.create_connection((host, port), timeout=_SOCKET_CONNECT_PROBE_TIMEOUT_SEC):
            return
    except OSError as exc:
        logger.warning(
            "Redis not reachable yet (host=%s port=%s). Worker will retry connection "
            "(conn_timeout=%ss conn_retries=%s conn_retry_delay=%ss). last_error=%s",
            host,
            port,
            redis_settings.conn_timeout,
            redis_settings.conn_retries,
            redis_settings.conn_retry_delay,
            str(exc)[:200],
        )


def _build_worker_redis_settings() -> RedisSettings:
    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
    redis_settings.conn_timeout = int(getattr(settings, "TASK_WORKER_REDIS_CONN_TIMEOUT_SEC", 1) or 1)
    redis_settings.conn_retries = int(getattr(settings, "TASK_WORKER_REDIS_CONN_RETRIES", 60) or 60)
    redis_settings.conn_retry_delay = int(getattr(settings, "TASK_WORKER_REDIS_CONN_RETRY_DELAY_SEC", 1) or 1)
    _warn_if_redis_unreachable(redis_settings)
    return redis_settings


async def _heartbeat_loop(
    *,
    redis: Any,
    queue_name: str,
    worker_id: str,
    interval: float,
    observe: Callable[..., Awaitable[Any]],
) -> None:
    while True:
        try:
            await observe(redis=redis, queue_name=queue_name, worker_id=worker_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("Worker heartbeat failed; retrying: %s", str(exc)[:200])
        await asyncio.sleep(interval)


def _log_heartbeat_task_exit(task: asyncio.Task[None]) -> None:
    if task.cancelled():
        return
    try:
        error = task.exception()
    except asyncio.CancelledError:
        return
    if error is not None:
        logger.error("Worker heartbeat task exited unexpectedly: %s", str(error)[:200])


async def startup(ctx):  # noqa: ANN001
    logger.info("Arq worker starting... max_jobs=%s", getattr(settings, "TASK_WORKER_MAX_JOBS", 10))
    try:
        from app.services.task_queue_observability_service import observe_task_worker_heartbeat

        queue_name = str(getattr(settings, "TASK_QUEUE_NAME", "mimirq") or "mimirq")
        worker_id = f"{socket.gethostname()}:{os.getpid()}"
        interval = float(getattr(settings, "TASK_WORKER_HEARTBEAT_INTERVAL_SEC", 5.0) or 5.0)
        interval = max(1.0, interval)

        # Fire-and-forget: never block worker startup.
        heartbeat_task = asyncio.create_task(
            _heartbeat_loop(
                redis=ctx.get("redis"),
                queue_name=queue_name,
                worker_id=worker_id,
                interval=interval,
                observe=observe_task_worker_heartbeat,
            )
        )
        heartbeat_task.add_done_callback(_log_heartbeat_task_exit)
        ctx[_WORKER_HEARTBEAT_TASK_KEY] = heartbeat_task
        logger.info("Worker heartbeat enabled queue=%s interval_sec=%s", queue_name, interval)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to start worker heartbeat: %s", str(exc)[:200])
    await asyncio.sleep(0)


async def shutdown(ctx):  # noqa: ANN001
    logger.info("Arq worker shutting down...")
    task = ctx.get(_WORKER_HEARTBEAT_TASK_KEY)
    if task is not None:
        try:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        finally:
            ctx.pop(_WORKER_HEARTBEAT_TASK_KEY, None)


class WorkerSettings:
    redis_settings = _build_worker_redis_settings()
    queue_name = getattr(settings, "TASK_QUEUE_NAME", "mimirq")
    functions = [
        func(
            process_document_job,
            max_tries=int(getattr(settings, "TASK_DOCUMENT_JOB_MAX_TRIES", 80) or 80),
        ),
        func(
            extract_kg_job,
            max_tries=int(getattr(settings, "TASK_KG_JOB_MAX_TRIES", 80) or 80),
        ),
        rebuild_indexes_job,
        dataset_profile_scan_job,
        dataset_precheck_scan_job,
        evidence_reference_sources_repair_job,
        connector_run_job,
        ping_job,
    ]
    max_jobs = int(getattr(settings, "TASK_WORKER_MAX_JOBS", 10) or 10)
    job_timeout = int(getattr(settings, "TASK_JOB_TIMEOUT_SEC", 60 * 30) or 60 * 30)
    max_tries = int(getattr(settings, "TASK_JOB_MAX_TRIES", 80) or 80)
    allow_abort_jobs = True
    on_startup = startup
    on_shutdown = shutdown
