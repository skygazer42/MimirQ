"""
API-side queue operations: init queue connection and enqueue document jobs.

API compatibility:
- If TASK_QUEUE_ENABLED=false, callers can still use BackgroundTasks.
"""


import asyncio
import threading
from typing import Any
from uuid import UUID

from app.core.config import settings
from app.rag.core.logging import get_logger

logger = get_logger("tasks.queue")

# arq is optional: when TASK_QUEUE_ENABLED=false, do not require arq.
_queue: Any | None = None
_queue_lock = asyncio.Lock()


class TaskEnqueueRejectedError(RuntimeError):
    """Raised when the queue is enabled but the broker does not accept the job."""


_LIVE_ARQ_JOB_STATUSES = frozenset({"deferred", "queued", "in_progress"})
_LOCAL_ACTIVE_SCAN_RUNS: set[str] = set()
_LOCAL_ACTIVE_SCAN_RUNS_LOCK = threading.Lock()


def is_queue_initialized() -> bool:
    """Whether the global arq queue pool has been created."""
    return _queue is not None


def _redis_settings():
    # arq RedisSettings supports full DSN.
    from arq.connections import RedisSettings

    return RedisSettings.from_dsn(settings.REDIS_URL)


class WorkerHealthSettings:
    """Lightweight settings for ``arq --check`` without importing worker jobs."""

    redis_settings = _redis_settings()
    queue_name = getattr(settings, "TASK_QUEUE_NAME", "mimirq")


async def init_queue() -> None:
    """Initialize queue connection on startup (optional)."""
    global _queue
    if not bool(getattr(settings, "TASK_QUEUE_ENABLED", False)):
        return
    if _queue is not None:
        return
    async with _queue_lock:
        if _queue is not None:
            return
        from arq import create_pool

        _queue = await create_pool(_redis_settings())
        logger.info("Task queue initialized (arq) queue=%s", getattr(settings, "TASK_QUEUE_NAME", "mimirq"))


async def close_queue() -> None:
    """Close queue connection on shutdown."""
    global _queue
    if _queue is None:
        return
    try:
        await _queue.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to close task queue: %s", str(exc)[:200])
    finally:
        _queue = None


async def get_queue() -> Any | None:
    """Get queue connection (lazy init)."""
    if not bool(getattr(settings, "TASK_QUEUE_ENABLED", False)):
        return None
    if _queue is None:
        await init_queue()
    return _queue


async def get_task_job_status(job_id: str) -> str | None:
    """Return an ARQ job status, or ``None`` when the queue is disabled."""
    q = await get_queue()
    if q is None:
        return None
    from arq.jobs import Job

    queue_name = getattr(settings, "TASK_QUEUE_NAME", "mimirq")
    status = await Job(str(job_id), q, _queue_name=queue_name).status()
    return str(getattr(status, "value", status) or "").strip().lower() or None


async def _resolve_scan_job_handoff(job: Any, *, job_id: str | None) -> str | None:
    if job is not None:
        return getattr(job, "job_id", None) or job_id
    if not job_id:
        raise TaskEnqueueRejectedError("scan job was not accepted by arq")
    status = await get_task_job_status(job_id)
    if status in _LIVE_ARQ_JOB_STATUSES:
        return job_id
    raise TaskEnqueueRejectedError(f"scan job was not accepted by arq (status={status or 'missing'})")


def _local_scan_run_key(
    *,
    kind: str,
    tenant_id: UUID | str,
    dataset_id: UUID | str,
    scan_run_id: UUID | str,
) -> str:
    return f"{str(kind or '').strip().lower()}:{tenant_id}:{dataset_id}:{scan_run_id}"


def register_local_scan_run_active(
    *,
    kind: str,
    tenant_id: UUID | str,
    dataset_id: UUID | str,
    scan_run_id: UUID | str,
) -> str:
    key = _local_scan_run_key(
        kind=kind,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        scan_run_id=scan_run_id,
    )
    with _LOCAL_ACTIVE_SCAN_RUNS_LOCK:
        _LOCAL_ACTIVE_SCAN_RUNS.add(key)
    return key


def unregister_local_scan_run_active(
    *,
    kind: str,
    tenant_id: UUID | str,
    dataset_id: UUID | str,
    scan_run_id: UUID | str,
) -> None:
    key = _local_scan_run_key(
        kind=kind,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        scan_run_id=scan_run_id,
    )
    with _LOCAL_ACTIVE_SCAN_RUNS_LOCK:
        _LOCAL_ACTIVE_SCAN_RUNS.discard(key)


def is_local_scan_run_active(
    *,
    kind: str,
    tenant_id: UUID | str,
    dataset_id: UUID | str,
    scan_run_id: UUID | str,
) -> bool:
    key = _local_scan_run_key(
        kind=kind,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        scan_run_id=scan_run_id,
    )
    with _LOCAL_ACTIVE_SCAN_RUNS_LOCK:
        return key in _LOCAL_ACTIVE_SCAN_RUNS


async def enqueue_document_processing(
    *,
    tenant_id: UUID,
    document_id: UUID,
    requested_by: str,
    job_id: str | None = None,
) -> str | None:
    """
    Enqueue a document processing job.

    Returns:
        - task_id/job_id (queue enabled)
        - None (queue disabled)
    """
    q = await get_queue()
    if q is None:
        return None

    queue_name = getattr(settings, "TASK_QUEUE_NAME", "mimirq")
    # Arq job_id can dedupe (behavior depends on arq version); we still enforce
    # idempotency with Redis locks on the worker side.
    job = await q.enqueue_job(
        "process_document_job",
        str(tenant_id),
        str(document_id),
        requested_by,
        _queue_name=queue_name,
        _job_id=job_id,
        _job_try=1,
    )
    return getattr(job, "job_id", None) or job_id


async def enqueue_kg_extraction(
    *,
    tenant_id: UUID,
    document_id: UUID,
    requested_by: str,
    job_id: str | None = None,
    pipeline_hash: str | None = None,
    replace_existing: bool | None = None,
    prune_orphan_entities: bool | None = None,
    extract_relations: bool | None = None,
    extract_skills: bool | None = None,
    effective_options: dict[str, Any] | None = None,
) -> str | None:
    """Enqueue KG extraction job (returns None if queue disabled or deduped)."""
    q = await get_queue()
    if q is None:
        return None
    queue_name = getattr(settings, "TASK_QUEUE_NAME", "mimirq")
    job = await q.enqueue_job(
        "extract_kg_job",
        str(tenant_id),
        str(document_id),
        requested_by,
        bool(replace_existing) if replace_existing is not None else None,
        bool(prune_orphan_entities) if prune_orphan_entities is not None else None,
        bool(extract_relations) if extract_relations is not None else None,
        bool(extract_skills) if extract_skills is not None else None,
        str(pipeline_hash) if pipeline_hash is not None else None,
        dict(effective_options) if effective_options is not None else None,
        _queue_name=queue_name,
        _job_id=job_id,
        _job_try=1,
    )
    return getattr(job, "job_id", None) if job is not None else None


async def enqueue_rebuild_indexes(
    *,
    tenant_id: UUID,
    requested_by: str,
    document_id: UUID | None = None,
    job_id: str | None = None,
) -> str | None:
    """Enqueue index rebuild job (returns None if queue disabled or deduped)."""
    q = await get_queue()
    if q is None:
        return None
    queue_name = getattr(settings, "TASK_QUEUE_NAME", "mimirq")
    job = await q.enqueue_job(
        "rebuild_indexes_job",
        str(tenant_id),
        requested_by,
        str(document_id) if document_id is not None else None,
        _queue_name=queue_name,
        _job_id=job_id,
        _job_try=1,
    )
    return getattr(job, "job_id", None) if job is not None else None


async def enqueue_dataset_profile_scan(
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    scan_run_id: UUID,
    requested_by: str,
    job_id: str | None = None,
) -> str | None:
    """Enqueue a dataset profile deep scan job (returns None if queue disabled)."""
    q = await get_queue()
    if q is None:
        return None
    queue_name = getattr(settings, "TASK_QUEUE_NAME", "mimirq")
    job = await q.enqueue_job(
        "dataset_profile_scan_job",
        str(tenant_id),
        str(dataset_id),
        str(scan_run_id),
        requested_by,
        _queue_name=queue_name,
        _job_id=job_id,
        _job_try=1,
    )
    return await _resolve_scan_job_handoff(job, job_id=job_id)


async def enqueue_dataset_precheck_scan(
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    scan_run_id: UUID,
    requested_by: str,
    job_id: str | None = None,
) -> str | None:
    """Enqueue a dataset precheck scan job (returns None if queue disabled)."""
    q = await get_queue()
    if q is None:
        return None
    queue_name = getattr(settings, "TASK_QUEUE_NAME", "mimirq")
    job = await q.enqueue_job(
        "dataset_precheck_scan_job",
        str(tenant_id),
        str(dataset_id),
        str(scan_run_id),
        requested_by,
        _queue_name=queue_name,
        _job_id=job_id,
        _job_try=1,
    )
    return await _resolve_scan_job_handoff(job, job_id=job_id)


async def enqueue_connector_run(
    *,
    tenant_id: UUID,
    run_id: UUID,
    requested_by: str,
    job_id: str | None = None,
) -> str | None:
    """Enqueue a connector run job (returns None if queue disabled)."""
    q = await get_queue()
    if q is None:
        return None
    queue_name = getattr(settings, "TASK_QUEUE_NAME", "mimirq")
    job = await q.enqueue_job(
        "connector_run_job",
        str(tenant_id),
        str(run_id),
        requested_by,
        _queue_name=queue_name,
        _job_id=job_id,
        _job_try=1,
    )
    return getattr(job, "job_id", None) or job_id


async def enqueue_evidence_reference_sources_repair(
    *,
    tenant_id: UUID,
    suite_id: UUID,
    requested_by: str,
    apply: bool,
    allow_approved: bool,
    include_archived_items: bool,
    max_items: int,
    max_refs_per_item: int,
    max_changes: int,
    job_id: str | None = None,
) -> str | None:
    """
    Enqueue an EvidenceSuite reference_sources repair job (bounded).

    Returns:
        - task_id/job_id (queue enabled)
        - None (queue disabled)
    """
    q = await get_queue()
    if q is None:
        return None
    queue_name = getattr(settings, "TASK_QUEUE_NAME", "mimirq")
    job = await q.enqueue_job(
        "evidence_reference_sources_repair_job",
        str(tenant_id),
        str(suite_id),
        requested_by,
        bool(apply),
        bool(allow_approved),
        bool(include_archived_items),
        int(max_items or 0),
        int(max_refs_per_item or 0),
        int(max_changes or 0),
        _queue_name=queue_name,
        _job_id=job_id,
        _job_try=1,
    )
    return getattr(job, "job_id", None) or job_id
