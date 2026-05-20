"""
Queue job implementations (worker side).

Notes:
- Jobs must re-validate tenant/document ownership to avoid cross-tenant access.
- Jobs use best-effort Redis locks/semaphores to avoid duplicate work.
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

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.connector import ConnectorRun as DBConnectorRun
from app.models.dataset_precheck_scan import DatasetPrecheckScanRun as DBDatasetPrecheckScanRun
from app.models.dataset_profile_scan import DatasetProfileScanRun as DBDatasetProfileScanRun
from app.models.document import Document as DBDocument
from app.parsing.processors.processor import document_processor
from app.rag.core.logging import get_logger
from app.services.audit_log_service import audit_log_event
from app.services.dataset_precheck_scan_runner import run_dataset_precheck_scan
from app.services.dataset_profile_scan_runner import run_dataset_profile_deep_scan
from app.services.evidence_reference_repair_service import (
    EvidenceSuiteNotFoundError,
    repair_evidence_suite_reference_sources,
)
from app.storage.object.minio import is_minio_uri, minio_service, parse_minio_uri
from app.tasks.locks import (
    acquire_lock,
    dataset_acquire,
    dataset_release,
    get_retry_exc,
    make_lock_value,
    release_lock,
    tenant_acquire,
    tenant_release,
)

logger = get_logger("tasks.jobs")


def _kg_lock_flag(value: bool | None) -> str:
    if value is None:
        return "auto"
    return "1" if bool(value) else "0"
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
    try:
        try:
            redis = ctx.get("redis") if isinstance(ctx, dict) else None
        except Exception:  # noqa: BLE001
            redis = None

        if redis is not None:
            sem_key = await tenant_acquire(
                redis,
                tenant_id=tenant_id,
                kind="evidence_repair",
                limit=int(getattr(settings, "TASK_TENANT_MAX_CONCURRENCY_EVIDENCE_REPAIR", 0) or 0),
                ttl_sec=120,
            )
            lock_key = f"lock:evidence_repair:{tenant_id}:{suite_id}"
            lock_val = make_lock_value(requested_by)
            lock_ttl = 60 * 60  # 60 min
            acquired = await acquire_lock(redis, key=lock_key, value=lock_val, ttl_sec=lock_ttl)
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
            redis = ctx.get("redis") if isinstance(ctx, dict) else None
        except Exception:  # noqa: BLE001
            redis = None

        if redis is not None:
            sem_key = await tenant_acquire(
                redis,
                tenant_id=tenant_id,
                kind="connector",
                limit=int(getattr(settings, "TASK_TENANT_MAX_CONCURRENCY_CONNECTOR", 0) or 0),
                ttl_sec=120,
            )

            lock_key = f"lock:connector:{tenant_id}:{run_id}"
            lock_val = make_lock_value(requested_by)
            lock_ttl = 60 * 40  # 40 min
            acquired = await acquire_lock(redis, key=lock_key, value=lock_val, ttl_sec=lock_ttl)
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

        # Worker side dispatch: reuse existing executors.
        import app.api.v1.connectors as connectors_module

        if connector_id == "url_batch":
            await connectors_module._execute_url_batch_run(run_id=rid, tenant_id=tid, requested_by=requested_by)
        elif connector_id == "web_crawl":
            await connectors_module._execute_web_crawl_run(run_id=rid, tenant_id=tid, requested_by=requested_by)
        elif connector_id == "github_repo":
            await connectors_module._execute_github_repo_run(run_id=rid, tenant_id=tid, requested_by=requested_by)
        elif connector_id == "drive_files":
            await connectors_module._execute_drive_files_run(run_id=rid, tenant_id=tid, requested_by=requested_by)
        elif connector_id == "minio_bucket":
            await connectors_module._execute_minio_bucket_run(run_id=rid, tenant_id=tid, requested_by=requested_by)
        elif connector_id == "confluence_space":
            await connectors_module._execute_confluence_space_run(run_id=rid, tenant_id=tid, requested_by=requested_by)
        elif connector_id == "jira_project":
            await connectors_module._execute_jira_project_run(run_id=rid, tenant_id=tid, requested_by=requested_by)
        elif connector_id in {"mysql_catalog", "sqlserver_catalog"}:
            await connectors_module._execute_db_catalog_run(run_id=rid, tenant_id=tid, requested_by=requested_by)
        else:
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
        try:
            redis = ctx.get("redis") if isinstance(ctx, dict) else None
        except Exception:  # noqa: BLE001
            redis = None

        lock_val = make_lock_value(requested_by)
        lock_ttl = 60 * 40  # 40 min
        if redis is not None:
            # Per-tenant concurrency limit (doc).
            sem_key = await tenant_acquire(
                redis,
                tenant_id=tenant_id,
                kind="doc",
                limit=int(getattr(settings, "TASK_TENANT_MAX_CONCURRENCY_DOC", 0) or 0),
                ttl_sec=120,
            )
            dataset_sem_key = await dataset_acquire(
                redis,
                tenant_id=tenant_id,
                dataset_id=str(doc.dataset_id) if doc.dataset_id else "",
                kind="doc",
                limit=int(getattr(settings, "TASK_DATASET_MAX_CONCURRENCY_DOC", 0) or 0),
                ttl_sec=120,
            )
            acquired = await acquire_lock(redis, key=lock_key, value=lock_val, ttl_sec=lock_ttl)
            if not acquired:
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

        if is_minio_uri(raw_path):
            if not bool(getattr(settings, "MINIO_ENABLED", False)):
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
                ref = parse_minio_uri(raw_path)
            except ValueError:
                await document_processor._update_status(
                    db,
                    tid,
                    did,
                    "failed",
                    0,
                    "failed",
                    error_message="invalid_object_path",
                )
                return await _job_result(
                    ctx,
                    job_name="process_document_job",
                    ok=False,
                    started_at=t0,
                    reason="invalid_object_path",
                    progress=_job_progress(stage="failed", done=0, total=1),
                    tenant_id=tenant_id,
                    document_id=document_id,
                )

            if ref.bucket != str(getattr(settings, "MINIO_BUCKET_NAME", "")):
                await document_processor._update_status(
                    db,
                    tid,
                    did,
                    "failed",
                    0,
                    "failed",
                    error_message="object_bucket_denied",
                )
                return await _job_result(
                    ctx,
                    job_name="process_document_job",
                    ok=False,
                    started_at=t0,
                    reason="object_bucket_denied",
                    progress=_job_progress(stage="failed", done=0, total=1),
                    tenant_id=tenant_id,
                    document_id=document_id,
                )

            dataset_id = str(doc.dataset_id) if doc.dataset_id else str(tid)
            expected_object = minio_service.build_document_object_name(
                tenant_id=str(tid),
                dataset_id=dataset_id,
                document_id=str(did),
                extension=f".{(doc.file_type or '').lower()}",
            )
            if ref.object_name != expected_object:
                await document_processor._update_status(
                    db,
                    tid,
                    did,
                    "failed",
                    0,
                    "failed",
                    error_message="object_key_denied",
                )
                return await _job_result(
                    ctx,
                    job_name="process_document_job",
                    ok=False,
                    started_at=t0,
                    reason="object_key_denied",
                    progress=_job_progress(stage="failed", done=0, total=1),
                    tenant_id=tenant_id,
                    document_id=document_id,
                )

            temp_dir = (Path(settings.UPLOAD_DIR) / str(tid) / ".tmp").resolve(strict=False)
            suffix = f".{(doc.file_type or '').lower()}"
            temp_path = temp_dir / f"{did}.{uuid.uuid4().hex}{suffix}"
            try:
                await asyncio.to_thread(
                    minio_service.download_object_to_path,
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

        try:
            result = await document_processor.process_document(
                file_path=file_path,
                document_id=did,
                tenant_id=tid,
                parser_backend=parser_backend,
                chunk_strategy=chunk_strategy,
                db=db,
            )
        finally:
            if temp_path is not None:
                with contextlib.suppress(Exception):
                    temp_path.unlink(missing_ok=True)
        return await _job_result(
            ctx,
            job_name="process_document_job",
            ok=True,
            started_at=t0,
            progress=_job_progress(stage="completed", done=1, total=1),
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

        # Idempotent lock: avoid concurrent scans per dataset.
        try:
            redis = ctx.get("redis") if isinstance(ctx, dict) else None
        except Exception:  # noqa: BLE001
            redis = None

        lock_key = f"lock:dataset_profile_scan:{tenant_id}:{dataset_id}"
        lock_val = make_lock_value(requested_by)
        lock_ttl = 60 * 40  # 40 min

        if redis is not None:
            sem_key = await tenant_acquire(
                redis,
                tenant_id=tenant_id,
                kind="scan",
                limit=int(getattr(settings, "TASK_TENANT_MAX_CONCURRENCY_DOC", 0) or 0),
                ttl_sec=120,
            )
            acquired = await acquire_lock(redis, key=lock_key, value=lock_val, ttl_sec=lock_ttl)
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

        try:
            redis = ctx.get("redis") if isinstance(ctx, dict) else None
        except Exception:  # noqa: BLE001
            redis = None

        lock_key = f"lock:dataset_precheck_scan:{tenant_id}:{dataset_id}"
        lock_val = make_lock_value(requested_by)
        lock_ttl = 60 * 60  # 60 min

        if redis is not None:
            sem_key = await tenant_acquire(
                redis,
                tenant_id=tenant_id,
                kind="scan",
                limit=int(getattr(settings, "TASK_TENANT_MAX_CONCURRENCY_DOC", 0) or 0),
                ttl_sec=120,
            )
            acquired = await acquire_lock(redis, key=lock_key, value=lock_val, ttl_sec=lock_ttl)
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
) -> dict:  # noqa: ANN001
    """
    KG extraction job: extract events/entities from completed chunks and index them.
    """
    from app.models.dataset import Dataset
    from app.models.document import DocumentChunk
    from app.rag.kg.pipeline import extract_events
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
    kg_retry_defer_sec = max(2, int(getattr(settings, "TASK_KG_RETRY_DEFER_SEC", 30) or 30))
    try:
        try:
            redis = ctx.get("redis") if isinstance(ctx, dict) else None
        except Exception:  # noqa: BLE001
            redis = None

        if redis is not None:
            sem_key = await tenant_acquire(
                redis,
                tenant_id=tenant_id,
                kind="kg",
                limit=int(getattr(settings, "TASK_TENANT_MAX_CONCURRENCY_KG", 0) or 0),
                ttl_sec=120,
                retry_defer_sec=kg_retry_defer_sec,
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

        if redis is not None:
            dataset_sem_key = await dataset_acquire(
                redis,
                tenant_id=tenant_id,
                dataset_id=str(doc.dataset_id) if doc.dataset_id else "",
                kind="kg",
                limit=int(getattr(settings, "TASK_DATASET_MAX_CONCURRENCY_KG", 0) or 0),
                ttl_sec=120,
                retry_defer_sec=kg_retry_defer_sec,
            )

        # Versioning: default to the active pipeline version so extraction doesn't mix
        # multiple chunk versions for the same document.
        from app.core.pipeline_versions import get_active_pipeline_hash  # noqa: WPS433

        explicit_ph = str(pipeline_hash or "").strip() or None
        doc_ph = (
            get_active_pipeline_hash(doc.doc_metadata or {})
            or (doc.doc_metadata or {}).get("pipeline_hash")
            or None
        )
        selected_ph = explicit_ph or (str(doc_ph).strip() if doc_ph is not None else None) or "unknown"
        replace_key = _kg_lock_flag(replace_existing)
        prune_key = _kg_lock_flag(prune_orphan_entities)
        rel_key = _kg_lock_flag(extract_relations)
        skill_key = _kg_lock_flag(extract_skills)
        lock_key = f"lock:kg:{tenant_id}:{document_id}:{selected_ph}:{replace_key}:{prune_key}:{rel_key}:{skill_key}"
        lock_val = make_lock_value(requested_by)
        lock_ttl = 60 * 40  # 40 min
        if redis is not None:
            acquired = await acquire_lock(redis, key=lock_key, value=lock_val, ttl_sec=lock_ttl)
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

        events = await extract_events(
            [c.id for c in chunks],
            tenant_id=tid,
            chunks=chunks,
            index_options=index_options,
            ab_user_key=requested_by,
            extract_relations=extract_relations,
            extract_skills=extract_skills,
            replace_existing=replace_existing,
            prune_orphan_entities=prune_orphan_entities,
        )
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
        )
    finally:
        if redis is not None and lock_key and lock_val:
            await release_lock(redis, key=lock_key, value=lock_val)
        await dataset_release(redis, dataset_sem_key)
        await tenant_release(redis, sem_key)
        db.close()


async def rebuild_indexes_job(ctx, tenant_id: str, requested_by: str) -> dict:  # noqa: ANN001
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
    try:
        try:
            redis = ctx.get("redis") if isinstance(ctx, dict) else None
        except Exception:  # noqa: BLE001
            redis = None

        if redis is not None:
            sem_key = await tenant_acquire(
                redis,
                tenant_id=tenant_id,
                kind="rebuild",
                limit=int(getattr(settings, "TASK_TENANT_MAX_CONCURRENCY_DOC", 0) or 0),
                ttl_sec=120,
            )

        lock_key = f"lock:rebuild:{tenant_id}"
        lock_val = make_lock_value(requested_by)
        lock_ttl = 60 * 40  # 40 min
        if redis is not None:
            acquired = await acquire_lock(redis, key=lock_key, value=lock_val, ttl_sec=lock_ttl)
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

        Indexer(db).rebuild_tenant(tenant_id=tid, kinds=[IndexKind.CHUNK])
        return await _job_result(
            ctx,
            job_name="rebuild_indexes_job",
            ok=True,
            started_at=t0,
            tenant_id=tenant_id,
        )
    finally:
        if redis is not None and lock_key and lock_val:
            await release_lock(redis, key=lock_key, value=lock_val)
        await tenant_release(redis, sem_key)
        db.close()
