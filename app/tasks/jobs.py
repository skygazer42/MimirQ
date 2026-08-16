"""
Queue job implementations (worker side).

Notes:
- Jobs must re-validate tenant/document ownership to avoid cross-tenant access.
- Jobs require Redis locks/semaphores to avoid duplicate work.
"""

import asyncio
import contextlib
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy.exc import SQLAlchemyError

from app.core.async_bridge import run_coroutine_in_thread
from app.core.config import settings
from app.core.database import SessionLocal
from app.models.connector import ConnectorRun as DBConnectorRun
from app.models.dataset_precheck_scan import DatasetPrecheckScanRun as DBDatasetPrecheckScanRun
from app.models.dataset_profile_scan import DatasetProfileScanRun as DBDatasetProfileScanRun
from app.models.document import Document as DBDocument
from app.parsing.processors.processor import document_processor
from app.rag.core.logging import get_logger
from app.services.audit_log_service import audit_log_event
from app.services.connector_run_executor import execute_connector_run
from app.services.dataset_precheck_scan_runner import run_dataset_precheck_scan
from app.services.dataset_profile_scan_runner import run_dataset_profile_deep_scan
from app.services.evidence_reference_repair_service import (
    EvidenceSuiteNotFoundError,
    repair_evidence_suite_reference_sources,
)
from app.storage.object.runtime import is_object_storage_uri, resolve_document_object_reference
from app.tasks.locks import (
    acquire_lock,
    dataset_acquire,
    dataset_release,
    get_retry_exc,
    is_semaphore_busy_retry,
    make_lock_value,
    release_lock,
    task_job_lock_ttl_sec,
    task_semaphore_lease_ttl_sec,
    tenant_acquire,
    tenant_release,
)

logger = get_logger("tasks.jobs")

_TASK_SEMAPHORE_LEASE_TTL_SEC = task_semaphore_lease_ttl_sec()
_TASK_SEMAPHORE_ACQUIRE_WAIT_SEC = max(0.0, float(getattr(settings, "TASK_SEMAPHORE_ACQUIRE_WAIT_SEC", 5.0) or 0.0))
_TASK_LOCK_RETRY_DEFER_SEC = 30
_TASK_COORDINATION_UNAVAILABLE = "task_coordination_unavailable"
_TASK_CONCURRENCY_BUSY = "task_concurrency_busy"


def _log_cancelled_document_processing_error(exc: BaseException) -> None:
    logger.warning(
        "Document processor failed while its queue job was being cancelled",
        exc_info=(type(exc), exc, exc.__traceback__),
    )


async def _run_document_processing_without_blocking_event_loop(*args: Any, **kwargs: Any) -> Any:
    return await run_coroutine_in_thread(
        lambda: document_processor.process_document(*args, **kwargs),
        on_cancelled_worker_error=_log_cancelled_document_processing_error,
    )


def _task_job_lock_ttl_sec(*, minimum_sec: int = 40 * 60) -> int:
    return task_job_lock_ttl_sec(minimum_sec=minimum_sec)


def _kg_lock_flag(value: bool | None) -> str:
    if value is None:
        return "auto"
    return "1" if bool(value) else "0"


def _transition_document_index_channel_best_effort(
    db: Any,
    *,
    document: DBDocument | None,
    channel: str,
    status: str,
    error: str | None = None,
    increment_attempt: bool = False,
    commit: bool = True,
) -> None:
    if document is None:
        return
    try:
        from app.services.document_index_channel_service import transition_document_index_channel

        transition_document_index_channel(
            db,
            document=document,
            channel=channel,
            status=status,
            error=error,
            increment_attempt=increment_attempt,
            commit=commit,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Failed to persist document index channel transition in worker tenant=%s document=%s channel=%s status=%s: %s",
            getattr(document, "tenant_id", None),
            getattr(document, "id", None),
            str(channel or ""),
            str(status or ""),
            str(exc)[:200],
        )
TASK_JOB_RESULT_SCHEMA_V1 = "mimirq.task_job_result.v1"


def _job_progress(*, stage: str, done: int | None = None, total: int | None = None, **extra: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"stage": str(stage or "").strip() or "unknown"}
    if done is not None:
        payload["done"] = max(0, int(done))
    if total is not None:
        payload["total"] = max(0, int(total))
    for key, value in extra.items():
        if value is not None:
            payload[key] = value
    return payload


async def _record_job_outcome(ctx, payload: dict[str, Any]) -> None:  # noqa: ANN001
    try:
        redis = ctx.get("redis") if isinstance(ctx, dict) else None
    except Exception:  # noqa: BLE001
        redis = None
    if redis is None:
        return

    try:
        from app.services.task_queue_observability_service import observe_task_job_outcome

        await observe_task_job_outcome(
            redis=redis,
            queue_name=str(getattr(settings, "TASK_QUEUE_NAME", "") or "mimirq"),
            outcome=payload,
        )
    except Exception:  # noqa: BLE001
        return


async def _job_result(
    ctx,  # noqa: ANN001
    *,
    job_name: str,
    ok: bool,
    started_at: float,
    reason: str | None = None,
    progress: dict[str, Any] | None = None,
    **fields: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": TASK_JOB_RESULT_SCHEMA_V1,
        "job_name": str(job_name or "").strip() or "unknown_job",
        "ok": bool(ok),
        "reason": str(reason).strip() if reason is not None else None,
        "elapsed_sec": round(max(0.0, float(time.perf_counter() - started_at)), 3),
        "finished_at": datetime.now(UTC).isoformat(),
        "progress": progress or _job_progress(stage="completed" if ok else "failed", done=1 if ok else 0, total=1),
    }
    for key, value in fields.items():
        if value is not None:
            payload[key] = value
    await _record_job_outcome(ctx, payload)
    return payload


def _current_job_try(ctx) -> int:  # noqa: ANN001
    if not isinstance(ctx, dict):
        return 1
    try:
        return max(1, int(ctx.get("job_try") or 1))
    except (TypeError, ValueError):
        return 1


def _document_job_max_tries() -> int:
    return max(1, int(getattr(settings, "TASK_DOCUMENT_JOB_MAX_TRIES", 80) or 80))


def _task_job_max_tries() -> int:
    return max(1, int(getattr(settings, "TASK_JOB_MAX_TRIES", 80) or 80))


def _kg_job_max_tries() -> int:
    return max(1, int(getattr(settings, "TASK_KG_JOB_MAX_TRIES", 80) or 80))


def _raise_task_retry(*, defer_sec: int, cause: Exception | None = None) -> None:
    retry_cls = get_retry_exc()
    if cause is None:
        raise retry_cls(defer=int(defer_sec))
    raise retry_cls(defer=int(defer_sec)) from cause


def _task_queue_redis_or_retry(ctx, *, retry_defer_sec: int):  # noqa: ANN001, ANN201
    try:
        redis = ctx.get("redis") if isinstance(ctx, dict) else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("Task job redis lookup failed (retry): %s", str(exc)[:200])
        _raise_task_retry(defer_sec=retry_defer_sec, cause=exc)
    if redis is None:
        logger.warning("Task job redis unavailable (retry)")
        _raise_task_retry(defer_sec=retry_defer_sec)
    return redis


async def _acquire_task_lock_or_retry(
    redis: Any,
    *,
    key: str,
    value: str,
    ttl_sec: int,
    retry_defer_sec: int,
) -> bool:
    return await acquire_lock(
        redis,
        key=key,
        value=value,
        ttl_sec=ttl_sec,
        fail_open=False,
        retry_defer_sec=retry_defer_sec,
    )


async def _mark_document_failed_on_exhausted_retry(
    *,
    ctx,  # noqa: ANN001
    db,
    tenant_id: UUID,
    document_id: UUID,
    reason: str,
) -> bool:
    if _current_job_try(ctx) < _document_job_max_tries():
        return False
    try:
        await document_processor._update_status(
            db,
            tenant_id,
            document_id,
            "failed",
            0,
            "failed",
            error_message=reason,
        )
    except SQLAlchemyError as exc:
        db.rollback()
        raise RuntimeError("failed to persist document task terminal state") from exc
    return True


def _is_retry_error(exc: Exception) -> bool:
    retry_cls = get_retry_exc()
    return bool(retry_cls) and isinstance(exc, retry_cls)


def _coordination_retry_reason(exc: Exception) -> str:
    return _TASK_CONCURRENCY_BUSY if is_semaphore_busy_retry(exc) else _TASK_COORDINATION_UNAVAILABLE


def _mark_run_failed(db, run: Any, *, reason: str) -> None:  # noqa: ANN401
    run.status = "failed"
    run.error_message = reason
    run.finished_at = datetime.now(UTC)
    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise RuntimeError("failed to persist task run terminal state") from exc


async def ping_job(ctx) -> dict:  # noqa: ANN001
    """Queue healthcheck job (for E2E benchmark)."""
    t0 = time.perf_counter()
    return await _job_result(ctx, job_name="ping_job", ok=True, started_at=t0)


async def evidence_reference_sources_repair_job(  # noqa: ANN001
    ctx,
    tenant_id: str,
    suite_id: str,
    requested_by: str,
    apply: bool,
    allow_approved: bool,
    include_archived_items: bool,
    max_items: int,
    max_refs_per_item: int,
    max_changes: int,
) -> dict:
    """
    EvidenceSuite reference_sources repair job (bounded, retryable).

    Args:
        tenant_id: tenant UUID string
        suite_id: suite UUID string
        requested_by: account_id (for audit/logging only)
    """
    t0 = time.perf_counter()
    tid = UUID(tenant_id)
    sid = UUID(suite_id)

    db = SessionLocal()
    redis = None
    lock_key = None
    lock_val = None
    sem_key = None
    retry_defer_sec = _TASK_LOCK_RETRY_DEFER_SEC
    try:
        try:
            redis = _task_queue_redis_or_retry(ctx, retry_defer_sec=retry_defer_sec)
            sem_key = await tenant_acquire(
                redis,
                tenant_id=tenant_id,
                kind="evidence_repair",
                limit=int(getattr(settings, "TASK_TENANT_MAX_CONCURRENCY_EVIDENCE_REPAIR", 0) or 0),
                ttl_sec=_TASK_SEMAPHORE_LEASE_TTL_SEC,
                retry_defer_sec=retry_defer_sec,
                wait_timeout_sec=_TASK_SEMAPHORE_ACQUIRE_WAIT_SEC,
            )
            lock_key = f"lock:evidence_repair:{tenant_id}:{suite_id}"
            lock_val = make_lock_value(requested_by)
            lock_ttl = _task_job_lock_ttl_sec(minimum_sec=60 * 60)
            acquired = await _acquire_task_lock_or_retry(
                redis,
                key=lock_key,
                value=lock_val,
                ttl_sec=lock_ttl,
                retry_defer_sec=retry_defer_sec,
            )
        except Exception as exc:
            if not _is_retry_error(exc) or _current_job_try(ctx) < _task_job_max_tries():
                raise
            reason = _coordination_retry_reason(exc)
            return await _job_result(
                ctx,
                job_name="evidence_reference_sources_repair_job",
                ok=False,
                started_at=t0,
                reason=reason,
                progress=_job_progress(stage="failed", done=0, total=1),
                tenant_id=tenant_id,
                suite_id=suite_id,
            )
        if not acquired:
            logger.info("Skip evidence repair job due to active lock: %s", lock_key)
            return await _job_result(
                ctx,
                job_name="evidence_reference_sources_repair_job",
                ok=True,
                started_at=t0,
                reason="locked",
                progress=_job_progress(stage="locked", done=0, total=1),
                skipped="locked",
                tenant_id=tenant_id,
                suite_id=suite_id,
            )

        try:
            result = repair_evidence_suite_reference_sources(
                db,
                tenant_id=tid,
                suite_id=sid,
                apply=bool(apply),
                allow_approved=bool(allow_approved),
                include_archived_items=bool(include_archived_items),
                max_items=int(max_items or 0),
                max_refs_per_item=int(max_refs_per_item or 0),
                max_changes=int(max_changes or 0),
                actor_id=requested_by,
            )
        except EvidenceSuiteNotFoundError:
            return await _job_result(
                ctx,
                job_name="evidence_reference_sources_repair_job",
                ok=False,
                started_at=t0,
                reason="suite_not_found",
                progress=_job_progress(stage="missing", done=0, total=1),
                tenant_id=tenant_id,
                suite_id=suite_id,
            )

        # Best-effort job-level audit summary (PII-safe; no raw evidence content).
        try:
            audit_log_event(
                db,
                tenant_id=tid,
                actor_id=requested_by,
                action="evidence.reference_sources.repair.job",
                resource_type="evidence_suite",
                resource_id=str(suite_id),
                details={
                    "async": True,
                    "applied": bool(apply),
                    "allow_approved": bool(allow_approved),
                    "include_archived_items": bool(include_archived_items),
                    "max_items": int(max_items or 0),
                    "max_refs_per_item": int(max_refs_per_item or 0),
                    "max_changes": int(max_changes or 0),
                    "scanned_items": int(result.get("scanned_items") or 0),
                    "scanned_references": int(result.get("scanned_references") or 0),
                    "drifted_references": int(result.get("drifted_references") or 0),
                    "repaired_references": int(result.get("repaired_references") or 0),
                    "changes_truncated": bool(result.get("changes_truncated") is True),
                },
            )
            db.commit()
        except Exception:  # noqa: BLE001
            with contextlib.suppress(Exception):  # noqa: BLE001
                db.rollback()

        return await _job_result(
            ctx,
            job_name="evidence_reference_sources_repair_job",
            ok=True,
            started_at=t0,
            progress=_job_progress(
                stage="completed",
                done=int(result.get("scanned_items") or 0),
                total=int(result.get("scanned_items") or 0),
            ),
            tenant_id=tenant_id,
            suite_id=suite_id,
            result=result,
        )
    finally:
        if redis is not None and lock_key and lock_val:
            await release_lock(redis, key=lock_key, value=lock_val)
        await tenant_release(redis, sem_key)
        db.close()


async def connector_run_job(ctx, tenant_id: str, run_id: str, requested_by: str) -> dict:  # noqa: ANN001
    """
    Connector run job wrapper (sync connector executions).

    Dispatches to the existing connector executors based on connector_id.
    """
    t0 = time.perf_counter()
    tid = UUID(tenant_id)
    rid = UUID(run_id)

    db = SessionLocal()
    redis = None
    sem_key = None
    lock_key = None
    lock_val = None
    retry_defer_sec = _TASK_LOCK_RETRY_DEFER_SEC
    try:
        run = (
            db.query(DBConnectorRun)
            .filter(DBConnectorRun.id == rid, DBConnectorRun.tenant_id == tid)
            .first()
        )
        if not run:
            return await _job_result(
                ctx,
                job_name="connector_run_job",
                ok=False,
                started_at=t0,
                reason="run_not_found",
                progress=_job_progress(stage="missing", done=0, total=1),
                tenant_id=tenant_id,
                run_id=run_id,
            )

        connector_id = str(getattr(run, "connector_id", "") or "").strip()
        try:
            redis = _task_queue_redis_or_retry(ctx, retry_defer_sec=retry_defer_sec)
            sem_key = await tenant_acquire(
                redis,
                tenant_id=tenant_id,
                kind="connector",
                limit=int(getattr(settings, "TASK_TENANT_MAX_CONCURRENCY_CONNECTOR", 0) or 0),
                ttl_sec=_TASK_SEMAPHORE_LEASE_TTL_SEC,
                retry_defer_sec=retry_defer_sec,
                wait_timeout_sec=_TASK_SEMAPHORE_ACQUIRE_WAIT_SEC,
            )

            lock_key = f"lock:connector:{tenant_id}:{run_id}"
            lock_val = make_lock_value(requested_by)
            lock_ttl = _task_job_lock_ttl_sec()
            acquired = await _acquire_task_lock_or_retry(
                redis,
                key=lock_key,
                value=lock_val,
                ttl_sec=lock_ttl,
                retry_defer_sec=retry_defer_sec,
            )
        except Exception as exc:
            if not _is_retry_error(exc) or _current_job_try(ctx) < _task_job_max_tries():
                raise
            reason = _coordination_retry_reason(exc)
            _mark_run_failed(db, run, reason=reason)
            return await _job_result(
                ctx,
                job_name="connector_run_job",
                ok=False,
                started_at=t0,
                reason=reason,
                progress=_job_progress(stage="failed", done=0, total=1),
                tenant_id=tenant_id,
                run_id=run_id,
                connector_id=connector_id,
            )
        if not acquired:
            logger.info("Skip connector job due to active lock: %s", lock_key)
            return await _job_result(
                ctx,
                job_name="connector_run_job",
                ok=True,
                started_at=t0,
                reason="locked",
                progress=_job_progress(stage="locked", done=0, total=1),
                skipped="locked",
                tenant_id=tenant_id,
                run_id=run_id,
            )

        executed = await execute_connector_run(
            connector_id=connector_id,
            run_id=rid,
            tenant_id=tid,
            requested_by=requested_by,
        )
        if not executed:
            run.status = "failed"
            run.error_message = "unsupported_connector_id"
            run.finished_at = datetime.now(UTC)
            db.commit()
            return await _job_result(
                ctx,
                job_name="connector_run_job",
                ok=False,
                started_at=t0,
                reason="unsupported_connector_id",
                progress=_job_progress(stage="failed", done=0, total=1),
                tenant_id=tenant_id,
                run_id=run_id,
                connector_id=connector_id,
            )

        return await _job_result(
            ctx,
            job_name="connector_run_job",
            ok=True,
            started_at=t0,
            connector_id=connector_id,
            tenant_id=tenant_id,
            run_id=run_id,
        )
    finally:
        if redis is not None and lock_key and lock_val:
            await release_lock(redis, key=lock_key, value=lock_val)
        await tenant_release(redis, sem_key)
        db.close()


async def process_document_job(ctx, tenant_id: str, document_id: str, requested_by: str) -> dict:  # noqa: ANN001
    """
    Document processing job: parse -> chunk -> index.

    Args:
        tenant_id: tenant UUID string
        document_id: document UUID string
        requested_by: account_id (for audit/logging only)
    """
    t0 = time.perf_counter()
    tid = UUID(tenant_id)
    did = UUID(document_id)

    db = SessionLocal()
    redis = None
    lock_key = None
    lock_val = None
    ingest_lock_key = None
    ingest_lock_val = None
    sem_key = None
    dataset_sem_key = None
    retry_defer_sec = _TASK_LOCK_RETRY_DEFER_SEC
    try:
        # Re-validate tenant/document ownership.
        doc = (
            db.query(DBDocument)
            .filter(DBDocument.id == did, DBDocument.tenant_id == tid)
            .first()
        )
        if not doc:
            # Task can be considered complete (target missing).
            return await _job_result(
                ctx,
                job_name="process_document_job",
                ok=False,
                started_at=t0,
                reason="document_not_found",
                progress=_job_progress(stage="missing", done=0, total=1),
                tenant_id=tenant_id,
                document_id=document_id,
            )

        meta0 = doc.doc_metadata if isinstance(doc.doc_metadata, dict) else {}
        pipeline_hash = meta0.get("pipeline_hash") or "unknown"
        lock_key = f"lock:doc:{tenant_id}:{document_id}:{pipeline_hash}"
        ingest_lock_key = meta0.get("ingest_lock_key")
        ingest_lock_val = meta0.get("ingest_lock_value")

        # Idempotent lock: avoid duplicate concurrent processing per doc+pipeline.
        # - Use Redis SET NX EX
        # - TTL slightly above job_timeout to avoid permanent lock on worker crash
        lock_val = make_lock_value(requested_by)
        lock_ttl = _task_job_lock_ttl_sec()
        retry_defer_sec = int(getattr(settings, "TASK_DOCUMENT_RETRY_DEFER_SEC", 30) or 30)
        try:
            redis = _task_queue_redis_or_retry(ctx, retry_defer_sec=retry_defer_sec)
            sem_key = await tenant_acquire(
                redis,
                tenant_id=tenant_id,
                kind="doc",
                limit=int(getattr(settings, "TASK_TENANT_MAX_CONCURRENCY_DOC", 0) or 0),
                ttl_sec=_TASK_SEMAPHORE_LEASE_TTL_SEC,
                retry_defer_sec=retry_defer_sec,
                wait_timeout_sec=_TASK_SEMAPHORE_ACQUIRE_WAIT_SEC,
            )
            dataset_sem_key = await dataset_acquire(
                redis,
                tenant_id=tenant_id,
                dataset_id=str(doc.dataset_id) if doc.dataset_id else "",
                kind="doc",
                limit=int(getattr(settings, "TASK_DATASET_MAX_CONCURRENCY_DOC", 0) or 0),
                ttl_sec=_TASK_SEMAPHORE_LEASE_TTL_SEC,
                retry_defer_sec=retry_defer_sec,
                wait_timeout_sec=_TASK_SEMAPHORE_ACQUIRE_WAIT_SEC,
            )
            acquired = await _acquire_task_lock_or_retry(
                redis,
                key=lock_key,
                value=lock_val,
                ttl_sec=lock_ttl,
                retry_defer_sec=retry_defer_sec,
            )
        except Exception as exc:
            if not _is_retry_error(exc):
                raise
            reason = _coordination_retry_reason(exc)
            if not await _mark_document_failed_on_exhausted_retry(
                ctx=ctx,
                db=db,
                tenant_id=tid,
                document_id=did,
                reason=reason,
            ):
                raise
            return await _job_result(
                ctx,
                job_name="process_document_job",
                ok=False,
                started_at=t0,
                reason=reason,
                progress=_job_progress(stage="failed", done=0, total=1),
                tenant_id=tenant_id,
                document_id=document_id,
                pipeline_hash=pipeline_hash,
            )
        if not acquired:
            exhausted = await _mark_document_failed_on_exhausted_retry(
                ctx=ctx,
                db=db,
                tenant_id=tid,
                document_id=did,
                reason="document_processing_lock_timeout",
            )
            if exhausted:
                return await _job_result(
                    ctx,
                    job_name="process_document_job",
                    ok=False,
                    started_at=t0,
                    reason="document_processing_lock_timeout",
                    progress=_job_progress(stage="failed", done=0, total=1),
                    tenant_id=tenant_id,
                    document_id=document_id,
                    pipeline_hash=pipeline_hash,
                )
            logger.info("Skip document job due to active lock: %s", lock_key)
            return await _job_result(
                ctx,
                job_name="process_document_job",
                ok=True,
                started_at=t0,
                reason="locked",
                progress=_job_progress(stage="locked", done=0, total=1),
                skipped="locked",
                tenant_id=tenant_id,
                document_id=document_id,
                pipeline_hash=pipeline_hash,
            )

        # Validation passed: execute document processing.
        parser_backend = (doc.doc_metadata or {}).get("parser_backend")
        chunk_strategy = (doc.doc_metadata or {}).get("chunk_strategy")

        raw_path = str(getattr(doc, "file_path", "") or "").strip()
        file_path: Path | None = None
        temp_path: Path | None = None

        if not raw_path or raw_path.startswith("manual://"):
            await document_processor._update_status(
                db,
                tid,
                did,
                "failed",
                0,
                "failed",
                error_message="document_file_not_available",
            )
            return await _job_result(
                ctx,
                job_name="process_document_job",
                ok=False,
                started_at=t0,
                reason="document_file_not_available",
                progress=_job_progress(stage="failed", done=0, total=1),
                tenant_id=tenant_id,
                document_id=document_id,
            )

        if is_object_storage_uri(raw_path):
            if not bool(getattr(settings, "MINIO_ENABLED", False)) and not bool(
                getattr(settings, "OBJECT_STORAGE_ENABLED", False)
            ):
                await document_processor._update_status(
                    db,
                    tid,
                    did,
                    "failed",
                    0,
                    "failed",
                    error_message="object_storage_disabled",
                )
                return await _job_result(
                    ctx,
                    job_name="process_document_job",
                    ok=False,
                    started_at=t0,
                    reason="object_storage_disabled",
                    progress=_job_progress(stage="failed", done=0, total=1),
                    tenant_id=tenant_id,
                    document_id=document_id,
                )
            try:
                store, ref = resolve_document_object_reference(
                    raw_path,
                    tenant_id=tid,
                    dataset_id=doc.dataset_id,
                    document_id=did,
                    file_type=doc.file_type,
                    document_metadata=dict(getattr(doc, "doc_metadata", None) or {}),
                )
            except RuntimeError:
                await document_processor._update_status(
                    db,
                    tid,
                    did,
                    "failed",
                    0,
                    "failed",
                    error_message="object_storage_disabled",
                )
                return await _job_result(
                    ctx,
                    job_name="process_document_job",
                    ok=False,
                    started_at=t0,
                    reason="object_storage_disabled",
                    progress=_job_progress(stage="failed", done=0, total=1),
                    tenant_id=tenant_id,
                    document_id=document_id,
                )
            except ValueError as exc:
                reason = str(exc) if str(exc) in {"object_bucket_denied", "object_key_denied"} else "invalid_object_path"
                await document_processor._update_status(
                    db,
                    tid,
                    did,
                    "failed",
                    0,
                    "failed",
                    error_message=reason,
                )
                return await _job_result(
                    ctx,
                    job_name="process_document_job",
                    ok=False,
                    started_at=t0,
                    reason=reason,
                    progress=_job_progress(stage="failed", done=0, total=1),
                    tenant_id=tenant_id,
                    document_id=document_id,
                )

            temp_dir = (Path(settings.UPLOAD_DIR) / str(tid) / ".tmp").resolve(strict=False)
            suffix = f".{(doc.file_type or '').lower()}"
            temp_path = temp_dir / f"{did}.{uuid.uuid4().hex}{suffix}"
            try:
                await asyncio.to_thread(
                    store.download_object_to_path,
                    object_name=ref.object_name,
                    destination=temp_path,
                    max_bytes=int(getattr(settings, "MAX_FILE_SIZE", 0) or 0),
                )
            except Exception as exc:  # noqa: BLE001
                with contextlib.suppress(Exception):
                    temp_path.unlink(missing_ok=True)
                await document_processor._update_status(
                    db,
                    tid,
                    did,
                    "failed",
                    0,
                    "failed",
                    error_message=str(exc)[:200],
                )
                return await _job_result(
                    ctx,
                    job_name="process_document_job",
                    ok=False,
                    started_at=t0,
                    reason="download_failed",
                    progress=_job_progress(stage="failed", done=0, total=1),
                    tenant_id=tenant_id,
                    document_id=document_id,
                )
            file_path = temp_path
        else:
            file_path = Path(raw_path)
            if not file_path.exists() or not file_path.is_file():
                await document_processor._update_status(
                    db,
                    tid,
                    did,
                    "failed",
                    0,
                    "failed",
                    error_message="document_file_not_found",
                )
                return await _job_result(
                    ctx,
                    job_name="process_document_job",
                    ok=False,
                    started_at=t0,
                    reason="document_file_not_found",
                    progress=_job_progress(stage="missing", done=0, total=1),
                    tenant_id=tenant_id,
                    document_id=document_id,
                )

        logger.info(
            "Processing document job: tenant_id=%s document_id=%s requested_by=%s",
            tenant_id,
            document_id,
            requested_by,
        )

        # The processor owns its session on the worker thread. Keeping the
        # preflight session here would cross SQLAlchemy's thread-safety boundary.
        db.close()
        try:
            result = await _run_document_processing_without_blocking_event_loop(
                file_path=file_path,
                document_id=did,
                tenant_id=tid,
                parser_backend=parser_backend,
                chunk_strategy=chunk_strategy,
                db=None,
            )
        finally:
            if temp_path is not None:
                with contextlib.suppress(Exception):
                    temp_path.unlink(missing_ok=True)
        result_status = str(result.get("status") or "").strip().lower() if isinstance(result, dict) else ""
        succeeded = result_status == "success"
        return await _job_result(
            ctx,
            job_name="process_document_job",
            ok=succeeded,
            started_at=t0,
            reason=(str(result.get("reason") or result_status or "processing_failed") if not succeeded else None),
            progress=_job_progress(
                stage="completed" if succeeded else (result_status or "failed"),
                done=1 if succeeded else 0,
                total=1,
            ),
            tenant_id=tenant_id,
            document_id=document_id,
            pipeline_hash=pipeline_hash,
            result=result,
        )
    finally:
        if redis is not None and lock_key and lock_val:
            await release_lock(redis, key=lock_key, value=lock_val)
        if redis is not None and ingest_lock_key and ingest_lock_val:
            await release_lock(redis, key=ingest_lock_key, value=ingest_lock_val)
        await dataset_release(redis, dataset_sem_key)
        await tenant_release(redis, sem_key)
        db.close()


async def dataset_profile_scan_job(ctx, tenant_id: str, dataset_id: str, scan_run_id: str, requested_by: str) -> dict:  # noqa: ANN001
    """
    Dataset profile deep scan job: best-effort backfill missing document metrics and persist a summary.

    Args:
        tenant_id: tenant UUID string
        dataset_id: dataset UUID string
        scan_run_id: scan run UUID string
        requested_by: account_id (for permission semantics + audit)
    """
    t0 = time.perf_counter()
    tid = UUID(tenant_id)
    dsid = UUID(dataset_id)
    rid = UUID(scan_run_id)

    db = SessionLocal()
    redis = None
    lock_key = None
    lock_val = None
    sem_key = None
    retry_defer_sec = _TASK_LOCK_RETRY_DEFER_SEC
    try:
        # Ensure scan run exists under tenant/dataset.
        run = (
            db.query(DBDatasetProfileScanRun)
            .filter(
                DBDatasetProfileScanRun.id == rid,
                DBDatasetProfileScanRun.tenant_id == tid,
                DBDatasetProfileScanRun.dataset_id == dsid,
            )
            .first()
        )
        if run is None:
            return await _job_result(
                ctx,
                job_name="dataset_profile_scan_job",
                ok=False,
                started_at=t0,
                reason="scan_run_not_found",
                progress=_job_progress(stage="missing", done=0, total=1),
                tenant_id=tenant_id,
                dataset_id=dataset_id,
                scan_run_id=scan_run_id,
            )
        if str(getattr(run, "status", "") or "") != "pending":
            return await _job_result(
                ctx,
                job_name="dataset_profile_scan_job",
                ok=True,
                started_at=t0,
                reason="scan_run_not_pending",
                progress=_job_progress(stage="skipped", done=1, total=1),
                skipped="scan_run_not_pending",
                tenant_id=tenant_id,
                dataset_id=dataset_id,
                scan_run_id=scan_run_id,
            )

        # Idempotent lock: avoid concurrent scans per dataset.
        lock_key = f"lock:dataset_profile_scan:{tenant_id}:{dataset_id}"
        lock_val = make_lock_value(requested_by)
        lock_ttl = _task_job_lock_ttl_sec()

        try:
            redis = _task_queue_redis_or_retry(ctx, retry_defer_sec=retry_defer_sec)
            sem_key = await tenant_acquire(
                redis,
                tenant_id=tenant_id,
                kind="scan",
                limit=int(getattr(settings, "TASK_TENANT_MAX_CONCURRENCY_DOC", 0) or 0),
                ttl_sec=_TASK_SEMAPHORE_LEASE_TTL_SEC,
                retry_defer_sec=retry_defer_sec,
                wait_timeout_sec=_TASK_SEMAPHORE_ACQUIRE_WAIT_SEC,
            )
            acquired = await _acquire_task_lock_or_retry(
                redis,
                key=lock_key,
                value=lock_val,
                ttl_sec=lock_ttl,
                retry_defer_sec=retry_defer_sec,
            )
        except Exception as exc:
            if not _is_retry_error(exc) or _current_job_try(ctx) < _task_job_max_tries():
                raise
            reason = _coordination_retry_reason(exc)
            _mark_run_failed(db, run, reason=reason)
            return await _job_result(
                ctx,
                job_name="dataset_profile_scan_job",
                ok=False,
                started_at=t0,
                reason=reason,
                progress=_job_progress(stage="failed", done=0, total=1),
                tenant_id=tenant_id,
                dataset_id=dataset_id,
                scan_run_id=scan_run_id,
            )
        if not acquired:
            logger.info("Skip dataset scan job due to active lock: %s", lock_key)
            return await _job_result(
                ctx,
                job_name="dataset_profile_scan_job",
                ok=True,
                started_at=t0,
                reason="locked",
                progress=_job_progress(stage="locked", done=0, total=1),
                skipped="locked",
                tenant_id=tenant_id,
                dataset_id=dataset_id,
                scan_run_id=scan_run_id,
            )

        # Execute deep scan (sync, best-effort).
        try:
            result = run_dataset_profile_deep_scan(
                db,
                tenant_id=tid,
                account_id=requested_by,
                dataset_id=dsid,
                scan_run_id=rid,
            )
        except Exception as exc:  # noqa: BLE001
            # Mark run failed.
            try:
                run = (
                    db.query(DBDatasetProfileScanRun)
                    .filter(
                        DBDatasetProfileScanRun.id == rid,
                        DBDatasetProfileScanRun.tenant_id == tid,
                        DBDatasetProfileScanRun.dataset_id == dsid,
                    )
                    .first()
                )
                if run is not None:
                    run.status = "failed"
                    run.error_message = str(exc)[:200]
                    run.finished_at = datetime.now(UTC)
                    db.commit()
            except SQLAlchemyError as exc:
                logger.debug("Ignoring non-critical task job rollback fallback failure: %s", exc)
            raise

        return await _job_result(
            ctx,
            job_name="dataset_profile_scan_job",
            ok=True,
            started_at=t0,
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            scan_run_id=scan_run_id,
            result=result,
        )
    finally:
        if redis is not None and lock_key and lock_val:
            await release_lock(redis, key=lock_key, value=lock_val)
        await tenant_release(redis, sem_key)
        db.close()


async def dataset_precheck_scan_job(ctx, tenant_id: str, dataset_id: str, scan_run_id: str, requested_by: str) -> dict:  # noqa: ANN001
    """
    Dataset precheck scan job: scan a local folder (before ingestion) and persist a summary.

    Args:
        tenant_id: tenant UUID string
        dataset_id: dataset UUID string
        scan_run_id: scan run UUID string
        requested_by: account_id (for audit)
    """
    t0 = time.perf_counter()
    tid = UUID(tenant_id)
    dsid = UUID(dataset_id)
    rid = UUID(scan_run_id)

    db = SessionLocal()
    redis = None
    lock_key = None
    lock_val = None
    sem_key = None
    retry_defer_sec = _TASK_LOCK_RETRY_DEFER_SEC
    try:
        run = (
            db.query(DBDatasetPrecheckScanRun)
            .filter(
                DBDatasetPrecheckScanRun.id == rid,
                DBDatasetPrecheckScanRun.tenant_id == tid,
                DBDatasetPrecheckScanRun.dataset_id == dsid,
            )
            .first()
        )
        if run is None:
            return await _job_result(
                ctx,
                job_name="dataset_precheck_scan_job",
                ok=False,
                started_at=t0,
                reason="scan_run_not_found",
                progress=_job_progress(stage="missing", done=0, total=1),
                tenant_id=tenant_id,
                dataset_id=dataset_id,
                scan_run_id=scan_run_id,
            )
        if str(getattr(run, "status", "") or "") != "pending":
            return await _job_result(
                ctx,
                job_name="dataset_precheck_scan_job",
                ok=True,
                started_at=t0,
                reason="scan_run_not_pending",
                progress=_job_progress(stage="skipped", done=1, total=1),
                skipped="scan_run_not_pending",
                tenant_id=tenant_id,
                dataset_id=dataset_id,
                scan_run_id=scan_run_id,
            )

        lock_key = f"lock:dataset_precheck_scan:{tenant_id}:{dataset_id}"
        lock_val = make_lock_value(requested_by)
        lock_ttl = _task_job_lock_ttl_sec(minimum_sec=60 * 60)

        try:
            redis = _task_queue_redis_or_retry(ctx, retry_defer_sec=retry_defer_sec)
            sem_key = await tenant_acquire(
                redis,
                tenant_id=tenant_id,
                kind="scan",
                limit=int(getattr(settings, "TASK_TENANT_MAX_CONCURRENCY_DOC", 0) or 0),
                ttl_sec=_TASK_SEMAPHORE_LEASE_TTL_SEC,
                retry_defer_sec=retry_defer_sec,
                wait_timeout_sec=_TASK_SEMAPHORE_ACQUIRE_WAIT_SEC,
            )
            acquired = await _acquire_task_lock_or_retry(
                redis,
                key=lock_key,
                value=lock_val,
                ttl_sec=lock_ttl,
                retry_defer_sec=retry_defer_sec,
            )
        except Exception as exc:
            if not _is_retry_error(exc) or _current_job_try(ctx) < _task_job_max_tries():
                raise
            reason = _coordination_retry_reason(exc)
            _mark_run_failed(db, run, reason=reason)
            return await _job_result(
                ctx,
                job_name="dataset_precheck_scan_job",
                ok=False,
                started_at=t0,
                reason=reason,
                progress=_job_progress(stage="failed", done=0, total=1),
                tenant_id=tenant_id,
                dataset_id=dataset_id,
                scan_run_id=scan_run_id,
            )
        if not acquired:
            logger.info("Skip dataset precheck scan job due to active lock: %s", lock_key)
            return await _job_result(
                ctx,
                job_name="dataset_precheck_scan_job",
                ok=True,
                started_at=t0,
                reason="locked",
                progress=_job_progress(stage="locked", done=0, total=1),
                skipped="locked",
                tenant_id=tenant_id,
                dataset_id=dataset_id,
                scan_run_id=scan_run_id,
            )

        try:
            result = run_dataset_precheck_scan(
                db,
                tenant_id=tid,
                dataset_id=dsid,
                scan_run_id=rid,
            )
        except Exception as exc:  # noqa: BLE001
            try:
                run = (
                    db.query(DBDatasetPrecheckScanRun)
                    .filter(
                        DBDatasetPrecheckScanRun.id == rid,
                        DBDatasetPrecheckScanRun.tenant_id == tid,
                        DBDatasetPrecheckScanRun.dataset_id == dsid,
                    )
                    .first()
                )
                if run is not None:
                    run.status = "failed"
                    run.error_message = str(exc)[:200]
                    run.finished_at = datetime.now(UTC)
                    db.commit()
            except SQLAlchemyError as exc:
                logger.debug("Ignoring non-critical task job rollback fallback failure: %s", exc)
            raise

        return await _job_result(
            ctx,
            job_name="dataset_precheck_scan_job",
            ok=True,
            started_at=t0,
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            scan_run_id=scan_run_id,
            result=result,
        )
    finally:
        if redis is not None and lock_key and lock_val:
            await release_lock(redis, key=lock_key, value=lock_val)
        await tenant_release(redis, sem_key)
        db.close()


async def extract_kg_job(
    ctx,
    tenant_id: str,
    document_id: str,
    requested_by: str,
    replace_existing: bool | None = None,
    prune_orphan_entities: bool | None = None,
    extract_relations: bool | None = None,
    extract_skills: bool | None = None,
    pipeline_hash: str | None = None,
    effective_options: dict[str, Any] | None = None,
) -> dict:  # noqa: ANN001
    """
    KG extraction job: extract events/entities from completed chunks and index them.
    """
    from app.models.dataset import Dataset
    from app.models.document import DocumentChunk
    from app.rag.kg.extraction_job_options import (
        kg_extraction_job_options_fingerprint,
        normalize_kg_extraction_job_options,
    )
    from app.rag.kg.pipeline import extract_events
    from app.rag.pipeline_plugins.registry import derive_registered_stage_plugin_ref
    from app.services.corpus_cache_tokens import invalidate_dataset_cache_namespace
    from app.services.pipeline_config import build_indexing_options, resolve_pipeline_effective

    t0 = time.perf_counter()
    tid = UUID(tenant_id)
    did = UUID(document_id)

    db = SessionLocal()
    redis = None
    sem_key = None
    dataset_sem_key = None
    lock_key = None
    lock_val = None
    doc: DBDocument | None = None
    kg_retry_defer_sec = max(2, int(getattr(settings, "TASK_KG_RETRY_DEFER_SEC", 30) or 30))
    try:
        frozen_options: dict[str, Any] | None = None
        if effective_options is not None:
            try:
                frozen_options = normalize_kg_extraction_job_options(effective_options)
            except ValueError:
                return await _job_result(
                    ctx,
                    job_name="extract_kg_job",
                    ok=False,
                    started_at=t0,
                    reason="invalid_effective_options",
                    progress=_job_progress(stage="failed", done=0, total=1),
                    tenant_id=tenant_id,
                    document_id=document_id,
                )
        queued_pipeline_hash = (
            str(frozen_options.get("pipeline_hash") or "").strip() if frozen_options is not None else ""
        ) or (str(pipeline_hash or "").strip() or None)

        try:
            redis = _task_queue_redis_or_retry(ctx, retry_defer_sec=kg_retry_defer_sec)
            kg_limit = int(getattr(settings, "TASK_TENANT_MAX_CONCURRENCY_KG", 0) or 0)
            sem_key = await tenant_acquire(
                redis,
                tenant_id=tenant_id,
                kind="kg",
                limit=kg_limit,
                ttl_sec=_TASK_SEMAPHORE_LEASE_TTL_SEC,
                retry_defer_sec=kg_retry_defer_sec,
                wait_timeout_sec=_TASK_SEMAPHORE_ACQUIRE_WAIT_SEC,
            )
        except Exception as exc:
            if not _is_retry_error(exc) or _current_job_try(ctx) < _kg_job_max_tries():
                raise
            reason = _coordination_retry_reason(exc)
            return await _job_result(
                ctx,
                job_name="extract_kg_job",
                ok=False,
                started_at=t0,
                reason=reason,
                progress=_job_progress(stage="failed", done=0, total=1),
                tenant_id=tenant_id,
                document_id=document_id,
                pipeline_hash=queued_pipeline_hash,
            )

        doc = db.query(DBDocument).filter(DBDocument.id == did, DBDocument.tenant_id == tid).first()
        if not doc:
            return await _job_result(
                ctx,
                job_name="extract_kg_job",
                ok=False,
                started_at=t0,
                reason="document_not_found",
                progress=_job_progress(stage="missing", done=0, total=1),
                tenant_id=tenant_id,
                document_id=document_id,
            )
        if (doc.status or "").lower() != "completed":
            # If not completed, retry later (ingest likely still running).
            retry_cls = get_retry_exc()
            if retry_cls:
                raise retry_cls(defer=5)
            return await _job_result(
                ctx,
                job_name="extract_kg_job",
                ok=False,
                started_at=t0,
                reason="document_not_completed",
                progress=_job_progress(stage="waiting", done=0, total=1),
                tenant_id=tenant_id,
                document_id=document_id,
                status=doc.status,
            )

        # Versioning: default to the active pipeline version so extraction doesn't mix
        # multiple chunk versions for the same document.
        from app.core.pipeline_versions import get_active_pipeline_hash  # noqa: WPS433

        explicit_ph = queued_pipeline_hash
        doc_ph = (
            get_active_pipeline_hash(doc.doc_metadata or {})
            or (doc.doc_metadata or {}).get("pipeline_hash")
            or None
        )
        selected_ph = explicit_ph or (str(doc_ph).strip() if doc_ph is not None else None) or "unknown"
        if frozen_options is not None:
            replace_existing = bool(frozen_options["replace_existing"])
            prune_orphan_entities = bool(frozen_options["prune_orphan_entities"])
            extract_relations = frozen_options["extract_relations"]
            extract_skills = frozen_options["extract_skills"]
            options_key = kg_extraction_job_options_fingerprint(frozen_options)
        else:
            options_key = ":".join(
                (
                    _kg_lock_flag(replace_existing),
                    _kg_lock_flag(prune_orphan_entities),
                    _kg_lock_flag(extract_relations),
                    _kg_lock_flag(extract_skills),
                )
            )
        lock_key = f"lock:kg:{tenant_id}:{document_id}:{selected_ph}:{options_key}"
        lock_val = make_lock_value(requested_by)
        lock_ttl = _task_job_lock_ttl_sec()
        try:
            dataset_sem_key = await dataset_acquire(
                redis,
                tenant_id=tenant_id,
                dataset_id=str(doc.dataset_id) if doc.dataset_id else "",
                kind="kg",
                limit=int(getattr(settings, "TASK_DATASET_MAX_CONCURRENCY_KG", 0) or 0),
                ttl_sec=_TASK_SEMAPHORE_LEASE_TTL_SEC,
                retry_defer_sec=kg_retry_defer_sec,
                wait_timeout_sec=_TASK_SEMAPHORE_ACQUIRE_WAIT_SEC,
            )
            acquired = await _acquire_task_lock_or_retry(
                redis,
                key=lock_key,
                value=lock_val,
                ttl_sec=lock_ttl,
                retry_defer_sec=kg_retry_defer_sec,
            )
        except Exception as exc:
            if not _is_retry_error(exc) or _current_job_try(ctx) < _kg_job_max_tries():
                raise
            reason = _coordination_retry_reason(exc)
            _transition_document_index_channel_best_effort(
                db,
                document=doc,
                channel="kg",
                status="error",
                error=reason,
            )
            return await _job_result(
                ctx,
                job_name="extract_kg_job",
                ok=False,
                started_at=t0,
                reason=reason,
                progress=_job_progress(stage="failed", done=0, total=1),
                tenant_id=tenant_id,
                document_id=document_id,
                pipeline_hash=selected_ph,
            )
        if not acquired:
            logger.info("Skip KG job due to active lock: %s", lock_key)
            return await _job_result(
                ctx,
                job_name="extract_kg_job",
                ok=True,
                started_at=t0,
                reason="locked",
                progress=_job_progress(stage="locked", done=0, total=1),
                skipped="locked",
                tenant_id=tenant_id,
                document_id=document_id,
                pipeline_hash=selected_ph,
            )

        chunks = (
            db.query(DocumentChunk)
            .filter(DocumentChunk.document_id == did, DocumentChunk.tenant_id == tid)
            .order_by(DocumentChunk.chunk_index)
            .all()
        )
        if not chunks:
            _transition_document_index_channel_best_effort(
                db,
                document=doc,
                channel="kg",
                status="error",
                error="no_chunks",
            )
            return await _job_result(
                ctx,
                job_name="extract_kg_job",
                ok=False,
                started_at=t0,
                reason="no_chunks",
                progress=_job_progress(stage="empty", done=0, total=1),
                tenant_id=tenant_id,
                document_id=document_id,
                pipeline_hash=selected_ph,
            )

        # Versioning: keep only chunks that belong to the selected pipeline hash.
        scoped_ph = str(selected_ph or "").strip() or None
        pipeline_scope_required = bool(explicit_ph or doc_ph)
        if scoped_ph:
            doc_key = f"{document_id}:{scoped_ph}"

            def _chunk_matches(c: DocumentChunk) -> bool:  # noqa: WPS430
                meta_any = getattr(c, "doc_metadata", None)
                if not isinstance(meta_any, dict):
                    return False
                key = str(meta_any.get("doc_pipeline_key") or "").strip()
                if key and key == doc_key:
                    return True
                ph = str(meta_any.get("pipeline_hash") or meta_any.get("active_pipeline_hash") or "").strip()
                return bool(ph and ph == scoped_ph)

            scoped = [c for c in chunks if _chunk_matches(c)]
            if scoped:
                chunks = scoped
            elif pipeline_scope_required:
                _transition_document_index_channel_best_effort(
                    db,
                    document=doc,
                    channel="kg",
                    status="error",
                    error="pipeline_chunks_not_found",
                )
                return await _job_result(
                    ctx,
                    job_name="extract_kg_job",
                    ok=False,
                    started_at=t0,
                    reason="pipeline_chunks_not_found",
                    progress=_job_progress(stage="failed", done=0, total=1),
                    tenant_id=tenant_id,
                    document_id=document_id,
                    pipeline_hash=selected_ph,
                )

        try:
            dataset_meta = {}
            if doc.dataset_id:
                ds = db.query(Dataset).filter(Dataset.id == doc.dataset_id, Dataset.tenant_id == tid).first()
                if ds is not None and isinstance(getattr(ds, "dataset_metadata", None), dict):
                    dataset_meta = dict(ds.dataset_metadata or {})

            effective = resolve_pipeline_effective(
                dataset_metadata=dataset_meta,
                document_metadata=(doc.doc_metadata or {}),
                request_overrides=None,
            )
            index_options = build_indexing_options(effective)
            if frozen_options is not None:
                prompt_template_id = (
                    UUID(str(frozen_options["prompt_template_id"])) if frozen_options["prompt_template_id"] else None
                )
                prompt_template_key = frozen_options["prompt_template_key"]
                prompt_ab_experiment_key = frozen_options["prompt_ab_experiment_key"]
                extraction_backend = frozen_options["extraction_backend"]
                kg_python_plugin_ref = str(frozen_options["kg_python_plugin"] or "").strip()
                kg_python_params = dict(frozen_options["kg_python_params"] or {})
            else:
                prompt_template_id = None
                prompt_template_key = None
                prompt_ab_experiment_key = None
                extraction_backend = None
                kg_python_plugin_ref = str(getattr(effective, "kg_python_plugin", "") or "").strip()
                if not kg_python_plugin_ref:
                    kg_python_plugin_ref = derive_registered_stage_plugin_ref(
                        str(getattr(effective, "chunk_python_plugin", "") or "").strip(),
                        "kg",
                    )
                kg_python_params = dict(getattr(effective, "kg_python_params", {}) or {})

            events = await extract_events(
                [c.id for c in chunks],
                tenant_id=tid,
                chunks=chunks,
                index_options=index_options,
                prompt_template_id=prompt_template_id,
                prompt_template_key=prompt_template_key,
                prompt_ab_experiment_key=prompt_ab_experiment_key,
                ab_user_key=requested_by,
                extract_relations=extract_relations,
                extract_skills=extract_skills,
                extraction_backend=extraction_backend,
                kg_python_plugin=kg_python_plugin_ref,
                kg_python_params=kg_python_params,
                replace_existing=replace_existing,
                prune_orphan_entities=prune_orphan_entities,
            )
        except Exception as exc:
            if _is_retry_error(exc) and _current_job_try(ctx) < _kg_job_max_tries():
                raise
            _transition_document_index_channel_best_effort(
                db,
                document=doc,
                channel="kg",
                status="error",
                error=str(exc)[:2000],
            )
            raise

        _transition_document_index_channel_best_effort(
            db,
            document=doc,
            channel="kg",
            status="ready",
        )
        if not events:
            for channel_name in ("event_vector", "entity_vector"):
                _transition_document_index_channel_best_effort(
                    db,
                    document=doc,
                    channel=channel_name,
                    status="skipped",
                )
        cache_invalidation: dict[str, Any] | None = None
        if doc.dataset_id:
            try:
                cache_invalidation = invalidate_dataset_cache_namespace(
                    db,
                    tenant_id=tid,
                    dataset_id=doc.dataset_id,
                )
                db.commit()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to invalidate dataset cache after KG extraction: %s", str(exc)[:200])
                with contextlib.suppress(Exception):
                    db.rollback()
        return await _job_result(
            ctx,
            job_name="extract_kg_job",
            ok=True,
            started_at=t0,
            progress=_job_progress(stage="completed", done=len(events), total=len(events)),
            tenant_id=tenant_id,
            document_id=document_id,
            pipeline_hash=selected_ph,
            event_count=len(events),
            cache_invalidation=cache_invalidation,
        )
    finally:
        if redis is not None and lock_key and lock_val:
            await release_lock(redis, key=lock_key, value=lock_val)
        await dataset_release(redis, dataset_sem_key)
        await tenant_release(redis, sem_key)
        db.close()


async def rebuild_indexes_job(
    ctx,
    tenant_id: str,
    requested_by: str,
    document_id: str | None = None,
) -> dict:  # noqa: ANN001
    """
    Rebuild indexes job (currently BM25; can extend to vectors/others).
    """
    from app.services.indexer import Indexer
    from app.types.indexing import IndexKind

    t0 = time.perf_counter()
    tid = UUID(tenant_id)
    db = SessionLocal()
    redis = None
    sem_key = None
    lock_key = None
    lock_val = None
    retry_defer_sec = _TASK_LOCK_RETRY_DEFER_SEC
    try:
        try:
            redis = _task_queue_redis_or_retry(ctx, retry_defer_sec=retry_defer_sec)
            sem_key = await tenant_acquire(
                redis,
                tenant_id=tenant_id,
                kind="rebuild",
                limit=int(getattr(settings, "TASK_TENANT_MAX_CONCURRENCY_DOC", 0) or 0),
                ttl_sec=_TASK_SEMAPHORE_LEASE_TTL_SEC,
                retry_defer_sec=retry_defer_sec,
                wait_timeout_sec=_TASK_SEMAPHORE_ACQUIRE_WAIT_SEC,
            )

            lock_scope = str(document_id).strip() if document_id is not None else "tenant"
            lock_key = f"lock:rebuild:{tenant_id}:{lock_scope}"
            lock_val = make_lock_value(requested_by)
            lock_ttl = _task_job_lock_ttl_sec()
            acquired = await _acquire_task_lock_or_retry(
                redis,
                key=lock_key,
                value=lock_val,
                ttl_sec=lock_ttl,
                retry_defer_sec=retry_defer_sec,
            )
        except Exception as exc:
            if not _is_retry_error(exc) or _current_job_try(ctx) < _task_job_max_tries():
                raise
            reason = _coordination_retry_reason(exc)
            return await _job_result(
                ctx,
                job_name="rebuild_indexes_job",
                ok=False,
                started_at=t0,
                reason=reason,
                progress=_job_progress(stage="failed", done=0, total=1),
                tenant_id=tenant_id,
            )
        if not acquired:
            logger.info("Skip rebuild job due to active lock: %s", lock_key)
            return await _job_result(
                ctx,
                job_name="rebuild_indexes_job",
                ok=True,
                started_at=t0,
                reason="locked",
                progress=_job_progress(stage="locked", done=0, total=1),
                skipped="locked",
                tenant_id=tenant_id,
            )

        document_uuid = UUID(str(document_id)) if document_id is not None else None
        document_ids = [document_uuid] if document_uuid is not None else None
        Indexer(db).rebuild_tenant(tenant_id=tid, document_ids=document_ids, kinds=[IndexKind.CHUNK])
        return await _job_result(
            ctx,
            job_name="rebuild_indexes_job",
            ok=True,
            started_at=t0,
            tenant_id=tenant_id,
            document_id=str(document_uuid) if document_uuid is not None else None,
        )
    finally:
        if redis is not None and lock_key and lock_val:
            await release_lock(redis, key=lock_key, value=lock_val)
        await tenant_release(redis, sem_key)
        db.close()


async def reconcile_index_audit_job(
    ctx,
    tenant_id: str,
    dataset_id: str,
    requested_by: str,
    document_id: str | None = None,
    limit: int = 100,
    dry_run: bool = True,
) -> dict:  # noqa: ANN001
    """
    Bounded tenant+dataset scoped index-audit reconcile scan.

    This job never scans all tenants. Dataset-only scans are bounded and report-only
    for legacy/no-row documents; rebuild enqueue remains document-scoped.
    """
    from app.services.index_audit_service import enqueue_index_audit_reconcile, plan_index_audit_reconcile

    t0 = time.perf_counter()
    tid = UUID(tenant_id)
    dsid = UUID(dataset_id)
    document_uuid = UUID(str(document_id)) if document_id is not None else None
    db = SessionLocal()
    redis = None
    sem_key = None
    lock_key = None
    lock_val = None
    retry_defer_sec = _TASK_LOCK_RETRY_DEFER_SEC
    try:
        try:
            redis = _task_queue_redis_or_retry(ctx, retry_defer_sec=retry_defer_sec)
            sem_key = await tenant_acquire(
                redis,
                tenant_id=tenant_id,
                kind="index_audit_reconcile",
                limit=int(getattr(settings, "TASK_TENANT_MAX_CONCURRENCY_DOC", 0) or 0),
                ttl_sec=_TASK_SEMAPHORE_LEASE_TTL_SEC,
                retry_defer_sec=retry_defer_sec,
                wait_timeout_sec=_TASK_SEMAPHORE_ACQUIRE_WAIT_SEC,
            )

            lock_scope = str(document_uuid) if document_uuid is not None else f"{dataset_id}:{int(limit or 0)}:{int(bool(dry_run))}"
            lock_key = f"lock:index-audit-reconcile:{tenant_id}:{lock_scope}"
            lock_val = make_lock_value(requested_by)
            lock_ttl = _task_job_lock_ttl_sec()
            acquired = await _acquire_task_lock_or_retry(
                redis,
                key=lock_key,
                value=lock_val,
                ttl_sec=lock_ttl,
                retry_defer_sec=retry_defer_sec,
            )
        except Exception as exc:
            if not _is_retry_error(exc) or _current_job_try(ctx) < _task_job_max_tries():
                raise
            reason = _coordination_retry_reason(exc)
            return await _job_result(
                ctx,
                job_name="reconcile_index_audit_job",
                ok=False,
                started_at=t0,
                reason=reason,
                progress=_job_progress(stage="failed", done=0, total=1),
                tenant_id=tenant_id,
                dataset_id=dataset_id,
                document_id=document_id,
            )
        if not acquired:
            logger.info("Skip index audit reconcile job due to active lock: %s", lock_key)
            return await _job_result(
                ctx,
                job_name="reconcile_index_audit_job",
                ok=True,
                started_at=t0,
                reason="locked",
                progress=_job_progress(stage="locked", done=0, total=1),
                skipped="locked",
                tenant_id=tenant_id,
                dataset_id=dataset_id,
                document_id=document_id,
            )

        plan = plan_index_audit_reconcile(
            db=db,
            tenant_id=tid,
            dataset_id=dsid,
            document_id=document_uuid,
            limit=int(limit or 0),
            dry_run=bool(dry_run),
        )
        if document_uuid is not None and int(plan.get("scanned_documents") or 0) <= 0:
            return await _job_result(
                ctx,
                job_name="reconcile_index_audit_job",
                ok=False,
                started_at=t0,
                reason="document_not_found",
                progress=_job_progress(stage="missing", done=0, total=1),
                tenant_id=tenant_id,
                dataset_id=dataset_id,
                document_id=document_id,
            )

        items_out: list[dict[str, Any]] = []
        candidate_documents = int(((plan.get("counts") if isinstance(plan.get("counts"), dict) else {}) or {}).get("candidate_documents") or 0)
        enqueued_count = 0
        already_queued_count = 0
        report_only_count = 0
        unsupported_count = 0
        for item in list(plan.get("items") or []):
            if not isinstance(item, dict):
                continue
            row = dict(item)
            action = str(row.get("action") or "report_only")
            if action != "enqueue_rebuild":
                row["enqueue_status"] = "report_only"
                report_only_count += 1
                items_out.append(row)
                continue
            if bool(dry_run):
                row["enqueue_status"] = "would_enqueue"
                items_out.append(row)
                continue

            reconcile = await enqueue_index_audit_reconcile(
                tenant_id=tid,
                dataset_id=dsid,
                document_id=UUID(str(row["document_id"])),
                requested_by=requested_by,
            )
            row["enqueue_status"] = str(reconcile.get("status") or "unknown")
            row["enqueue_reason"] = reconcile.get("reason")
            row["task_id"] = reconcile.get("task_id")
            if row["enqueue_status"] == "enqueued":
                enqueued_count += 1
            elif row["enqueue_status"] == "already_queued":
                already_queued_count += 1
            elif row["enqueue_status"] == "unsupported":
                unsupported_count += 1
            items_out.append(row)

        progress_stage = "planned" if bool(dry_run) else "completed"
        return await _job_result(
            ctx,
            job_name="reconcile_index_audit_job",
            ok=True,
            started_at=t0,
            progress=_job_progress(stage=progress_stage, done=len(items_out), total=int(plan.get("scanned_documents") or 0)),
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            document_id=document_id,
            dry_run=bool(dry_run),
            scan_limit=int(plan.get("scan_limit") or 0),
            scanned_documents=int(plan.get("scanned_documents") or 0),
            candidate_documents=candidate_documents,
            enqueued_count=enqueued_count,
            already_queued_count=already_queued_count,
            report_only_count=report_only_count,
            unsupported_count=unsupported_count,
            report={
                "schema": str(plan.get("schema") or "mimirq.index_audit_reconcile_plan.v1"),
                "scope": str(plan.get("scope") or ("document" if document_uuid is not None else "dataset")),
                "counts": dict(plan.get("counts") or {}) if isinstance(plan.get("counts"), dict) else {},
                "items": items_out,
            },
        )
    finally:
        if redis is not None and lock_key and lock_val:
            await release_lock(redis, key=lock_key, value=lock_val)
        await tenant_release(redis, sem_key)
        db.close()
