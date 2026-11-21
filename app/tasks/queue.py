"""
API-side queue operations: init queue connection and enqueue document jobs.

API compatibility:
- If TASK_QUEUE_ENABLED=false, callers can still use BackgroundTasks.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from app.infrastructure.config import settings

if TYPE_CHECKING:
    from arq.connections import ArqRedis, RedisSettings
    from arq.jobs import Job

logger = logging.getLogger("tasks.queue")

# arq is optional: when TASK_QUEUE_ENABLED=false, do not require arq.
_queue: ArqRedis | None = None
_queue_lock = asyncio.Lock()


class TaskEnqueueRejectedError(RuntimeError):
    """Raised when the queue is enabled but the broker does not accept the job."""


_LIVE_ARQ_JOB_STATUSES = frozenset({"deferred", "queued", "in_progress"})
_LOCAL_ACTIVE_SCAN_RUNS: set[str] = set()
_LOCAL_ACTIVE_SCAN_RUNS_LOCK = threading.Lock()


def is_queue_initialized() -> bool:
    """Whether the global arq queue pool has been created."""
    return _queue is not None


def _redis_settings() -> RedisSettings:
    # arq RedisSettings supports full DSN.
    from arq.connections import RedisSettings

    return RedisSettings.from_dsn(settings.REDIS_URL)


def __getattr__(name: str) -> type:
    if name != "WorkerHealthSettings":
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    # The CLI needs arq; importing API queue helpers must keep it optional.
    class WorkerHealthSettings:
        """Lightweight settings for ``arq --check`` without importing worker jobs."""

        redis_settings = _redis_settings()
        queue_name = settings.TASK_QUEUE_NAME

    globals()[name] = WorkerHealthSettings
    return WorkerHealthSettings


async def init_queue() -> None:
    """Initialize queue connection on startup (optional)."""
    global _queue
    if not settings.TASK_QUEUE_ENABLED:
        return
    if _queue is not None:
        return
    async with _queue_lock:
        if _queue is not None:
            return
        from arq import create_pool

        _queue = await create_pool(_redis_settings())
        logger.info("Task queue initialized (arq) queue=%s", settings.TASK_QUEUE_NAME)


async def close_queue() -> None:
    """Close queue connection on shutdown."""
    global _queue
    async with _queue_lock:
        queue = _queue
        _queue = None
        if queue is None:
            return
        try:
            await queue.close()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to close task queue: %s", str(exc)[:200])


async def get_queue() -> ArqRedis | None:
    """Get queue connection (lazy init)."""
    if not settings.TASK_QUEUE_ENABLED:
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

    queue_name = settings.TASK_QUEUE_NAME
    status = await Job(job_id, q, _queue_name=queue_name).status()
    return status.value


async def _resolve_job_handoff(job: Job | None, *, job_id: str | None) -> str:
    if job is not None:
        return job.job_id
    if not job_id:
        raise TaskEnqueueRejectedError("job was not accepted by arq")
    status = await get_task_job_status(job_id)
    if status in _LIVE_ARQ_JOB_STATUSES:
        return job_id
    raise TaskEnqueueRejectedError(f"job was not accepted by arq (status={status or 'missing'})")


async def _enqueue_job(name: str, *args: object, job_id: str | None) -> str | None:
    queue = await get_queue()
    if queue is None:
        return None
    job = await queue.enqueue_job(
        name,
        *args,
        _queue_name=settings.TASK_QUEUE_NAME,
        _job_id=job_id,
        _job_try=1,
    )
    return await _resolve_job_handoff(job, job_id=job_id)


def _local_scan_run_key(
    *,
    kind: str,
    tenant_id: UUID | str,
    dataset_id: UUID | str,
    scan_run_id: UUID | str,
) -> str:
    return f"{kind.strip().lower()}:{tenant_id}:{dataset_id}:{scan_run_id}"


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

    queue_name = settings.TASK_QUEUE_NAME

    async def submit(candidate_id: str | None) -> Job | None:
        return await q.enqueue_job(
            "process_document_job",
            str(tenant_id),
            str(document_id),
            requested_by,
            _queue_name=queue_name,
            _job_id=candidate_id,
            _job_try=1,
        )

    job = await submit(job_id)
    if job is not None:
        return job.job_id
    if job_id is None:
        raise TaskEnqueueRejectedError("document job was not accepted by arq")
    status = await get_task_job_status(job_id)
    if status in _LIVE_ARQ_JOB_STATUSES:
        return job_id
    if status != "complete":
        raise TaskEnqueueRejectedError(f"document job was not accepted by arq (status={status or 'missing'})")
    # ARQ retains completed results under the original ID, including failed attempts.
    attempt_id = f"{job_id}:attempt:{uuid4().hex}"
    return await _resolve_job_handoff(await submit(attempt_id), job_id=attempt_id)


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
    """Enqueue KG extraction or reuse a live job; return None only when disabled."""
    return await _enqueue_job(
        "extract_kg_job",
        str(tenant_id),
        str(document_id),
        requested_by,
        replace_existing,
        prune_orphan_entities,
        extract_relations,
        extract_skills,
        pipeline_hash,
        dict(effective_options) if effective_options is not None else None,
        job_id=job_id,
    )


async def enqueue_rebuild_indexes(
    *,
    tenant_id: UUID,
    requested_by: str,
    document_id: UUID | None = None,
    job_id: str | None = None,
) -> str | None:
    """Enqueue an index rebuild or reuse a live job; return None only when disabled."""
    return await _enqueue_job(
        "rebuild_indexes_job",
        str(tenant_id),
        requested_by,
        str(document_id) if document_id is not None else None,
        job_id=job_id,
    )


async def enqueue_index_audit_reconcile_job(
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    requested_by: str,
    document_id: UUID | None = None,
    limit: int = 100,
    dry_run: bool = True,
    job_id: str | None = None,
) -> str | None:
    """Enqueue a bounded tenant+dataset scoped index-audit reconcile job."""
    return await _enqueue_job(
        "reconcile_index_audit_job",
        str(tenant_id),
        str(dataset_id),
        requested_by,
        str(document_id) if document_id is not None else None,
        limit,
        dry_run,
        job_id=job_id,
    )


async def enqueue_dataset_profile_scan(
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    scan_run_id: UUID,
    requested_by: str,
    job_id: str | None = None,
) -> str | None:
    """Enqueue a dataset profile deep scan job (returns None if queue disabled)."""
    return await _enqueue_job(
        "dataset_profile_scan_job",
        str(tenant_id),
        str(dataset_id),
        str(scan_run_id),
        requested_by,
        job_id=job_id,
    )


async def enqueue_dataset_precheck_scan(
    *,
    tenant_id: UUID,
    dataset_id: UUID,
    scan_run_id: UUID,
    requested_by: str,
    job_id: str | None = None,
) -> str | None:
    """Enqueue a dataset precheck scan job (returns None if queue disabled)."""
    return await _enqueue_job(
        "dataset_precheck_scan_job",
        str(tenant_id),
        str(dataset_id),
        str(scan_run_id),
        requested_by,
        job_id=job_id,
    )


async def enqueue_connector_run(
    *,
    tenant_id: UUID,
    run_id: UUID,
    requested_by: str,
    job_id: str | None = None,
) -> str | None:
    """Enqueue a connector run job (returns None if queue disabled)."""
    return await _enqueue_job(
        "connector_run_job",
        str(tenant_id),
        str(run_id),
        requested_by,
        job_id=job_id,
    )


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
    return await _enqueue_job(
        "evidence_reference_sources_repair_job",
        str(tenant_id),
        str(suite_id),
        requested_by,
        apply,
        allow_approved,
        include_archived_items,
        max_items,
        max_refs_per_item,
        max_changes,
        job_id=job_id,
    )
