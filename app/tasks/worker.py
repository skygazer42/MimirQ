"""
Arq worker configuration entry.

Start method (container/local):
  arq app.tasks.worker.WorkerSettings
"""


import socket

from arq.connections import RedisSettings

from app.core.config import settings
from app.rag.core.logging import get_logger
from app.tasks.jobs import (
    connector_run_job,
    dataset_precheck_scan_job,
    dataset_profile_scan_job,
    extract_kg_job,
    ping_job,
    process_document_job,
    rebuild_indexes_job,
)

logger = get_logger("tasks.worker")

_SOCKET_CONNECT_PROBE_TIMEOUT_SEC = 0.2


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


async def startup(ctx):  # noqa: ANN001
    logger.info("Arq worker starting... max_jobs=%s", getattr(settings, "TASK_WORKER_MAX_JOBS", 10))


async def shutdown(ctx):  # noqa: ANN001
    logger.info("Arq worker shutting down...")


class WorkerSettings:
    redis_settings = _build_worker_redis_settings()
    queue_name = getattr(settings, "TASK_QUEUE_NAME", "mimirq")
    functions = [
        process_document_job,
        extract_kg_job,
        rebuild_indexes_job,
        dataset_profile_scan_job,
        dataset_precheck_scan_job,
        connector_run_job,
        ping_job,
    ]
    max_jobs = int(getattr(settings, "TASK_WORKER_MAX_JOBS", 10) or 10)
    job_timeout = int(getattr(settings, "TASK_JOB_TIMEOUT_SEC", 60 * 30) or 60 * 30)
    max_tries = int(getattr(settings, "TASK_JOB_MAX_TRIES", 3) or 3)
    allow_abort_jobs = True
    on_startup = startup
    on_shutdown = shutdown
