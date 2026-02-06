"""
Arq worker configuration entry.

Start method (container/local):
  arq app.tasks.worker.WorkerSettings
"""


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


async def startup(ctx):  # noqa: ANN001
    logger.info("Arq worker starting... max_jobs=%s", getattr(settings, "TASK_WORKER_MAX_JOBS", 10))


async def shutdown(ctx):  # noqa: ANN001
    logger.info("Arq worker shutting down...")


class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
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
