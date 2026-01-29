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
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from app.core.config import settings
from app.core.database import SessionLocal
from app.models.dataset_precheck_scan import DatasetPrecheckScanRun as DBDatasetPrecheckScanRun
from app.models.dataset_profile_scan import DatasetProfileScanRun as DBDatasetProfileScanRun
from app.models.document import Document as DBDocument
from app.parsing.processors.processor import document_processor
from app.rag.core.logging import get_logger
from app.services.dataset_precheck_scan_runner import run_dataset_precheck_scan
from app.services.dataset_profile_scan_runner import run_dataset_profile_deep_scan
from app.storage.object.minio import is_minio_uri, minio_service, parse_minio_uri
from app.tasks.locks import acquire_lock, get_retry_exc, make_lock_value, release_lock, tenant_acquire, tenant_release

logger = get_logger("tasks.jobs")


async def ping_job(ctx) -> dict:  # noqa: ANN001
    """Queue healthcheck job (for E2E benchmark)."""
    return {"ok": True}


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
    sem_key = None
    try:
        # Re-validate tenant/document ownership.
        doc = (
            db.query(DBDocument)
            .filter(DBDocument.id == did, DBDocument.tenant_id == tid)
            .first()
        )
        if not doc:
            # Task can be considered complete (target missing).
            return {"ok": False, "reason": "document_not_found", "tenant_id": tenant_id, "document_id": document_id}

        pipeline_hash = (doc.doc_metadata or {}).get("pipeline_hash") or "unknown"
        lock_key = f"lock:doc:{tenant_id}:{document_id}:{pipeline_hash}"

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
            acquired = await acquire_lock(redis, key=lock_key, value=lock_val, ttl_sec=lock_ttl)
            if not acquired:
                logger.info("Skip document job due to active lock: %s", lock_key)
                return {
                    "ok": True,
                    "skipped": "locked",
                    "tenant_id": tenant_id,
                    "document_id": document_id,
                    "pipeline_hash": pipeline_hash,
                }

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
            return {"ok": False, "reason": "document_file_not_available", "tenant_id": tenant_id, "document_id": document_id}

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
                return {"ok": False, "reason": "object_storage_disabled", "tenant_id": tenant_id, "document_id": document_id}
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
                return {"ok": False, "reason": "invalid_object_path", "tenant_id": tenant_id, "document_id": document_id}

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
                return {"ok": False, "reason": "object_bucket_denied", "tenant_id": tenant_id, "document_id": document_id}

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
                return {"ok": False, "reason": "object_key_denied", "tenant_id": tenant_id, "document_id": document_id}

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
                return {"ok": False, "reason": "download_failed", "tenant_id": tenant_id, "document_id": document_id}
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
                return {"ok": False, "reason": "document_file_not_found", "tenant_id": tenant_id, "document_id": document_id}

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
        elapsed = time.perf_counter() - t0
        return {"ok": True, "elapsed_sec": round(elapsed, 3), "result": result}
    finally:
        if redis is not None and lock_key and lock_val:
            await release_lock(redis, key=lock_key, value=lock_val)
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
            return {"ok": False, "reason": "scan_run_not_found", "tenant_id": tenant_id, "dataset_id": dataset_id, "scan_run_id": scan_run_id}

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
                return {
                    "ok": True,
                    "skipped": "locked",
                    "tenant_id": tenant_id,
                    "dataset_id": dataset_id,
                    "scan_run_id": scan_run_id,
                }

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
                    run.finished_at = datetime.now(timezone.utc)
                    db.commit()
            except Exception:
                pass
            raise

        elapsed = time.perf_counter() - t0
        return {"ok": True, "elapsed_sec": round(elapsed, 3), "result": result}
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
            return {
                "ok": False,
                "reason": "scan_run_not_found",
                "tenant_id": tenant_id,
                "dataset_id": dataset_id,
                "scan_run_id": scan_run_id,
            }

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
                return {
                    "ok": True,
                    "skipped": "locked",
                    "tenant_id": tenant_id,
                    "dataset_id": dataset_id,
                    "scan_run_id": scan_run_id,
                }

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
                    run.finished_at = datetime.now(timezone.utc)
                    db.commit()
            except Exception:
                pass
            raise

        elapsed = time.perf_counter() - t0
        return {"ok": True, "elapsed_sec": round(elapsed, 3), "result": result}
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
                kind="kg",
                limit=int(getattr(settings, "TASK_TENANT_MAX_CONCURRENCY_KG", 0) or 0),
                ttl_sec=120,
            )

        doc = db.query(DBDocument).filter(DBDocument.id == did, DBDocument.tenant_id == tid).first()
        if not doc:
            return {"ok": False, "reason": "document_not_found", "tenant_id": tenant_id, "document_id": document_id}
        if (doc.status or "").lower() != "completed":
            # If not completed, retry later (ingest likely still running).
            retry_cls = get_retry_exc()
            if retry_cls:
                raise retry_cls(defer=5)
            return {"ok": False, "reason": "document_not_completed", "status": doc.status}

        pipeline_hash = (doc.doc_metadata or {}).get("pipeline_hash") or "unknown"
        replace_key = "auto" if replace_existing is None else ("1" if bool(replace_existing) else "0")
        prune_key = "auto" if prune_orphan_entities is None else ("1" if bool(prune_orphan_entities) else "0")
        lock_key = f"lock:kg:{tenant_id}:{document_id}:{pipeline_hash}:{replace_key}:{prune_key}"
        lock_val = make_lock_value(requested_by)
        lock_ttl = 60 * 40  # 40 min
        if redis is not None:
            acquired = await acquire_lock(redis, key=lock_key, value=lock_val, ttl_sec=lock_ttl)
            if not acquired:
                logger.info("Skip KG job due to active lock: %s", lock_key)
                return {
                    "ok": True,
                    "skipped": "locked",
                    "tenant_id": tenant_id,
                    "document_id": document_id,
                    "pipeline_hash": pipeline_hash,
                }

        chunks = (
            db.query(DocumentChunk)
            .filter(DocumentChunk.document_id == did, DocumentChunk.tenant_id == tid)
            .order_by(DocumentChunk.chunk_index)
            .all()
        )
        if not chunks:
            return {"ok": False, "reason": "no_chunks", "tenant_id": tenant_id, "document_id": document_id}

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
            replace_existing=replace_existing,
            prune_orphan_entities=prune_orphan_entities,
        )
        elapsed = time.perf_counter() - t0
        return {"ok": True, "event_count": len(events), "elapsed_sec": round(elapsed, 3)}
    finally:
        if redis is not None and lock_key and lock_val:
            await release_lock(redis, key=lock_key, value=lock_val)
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
                return {"ok": True, "skipped": "locked", "tenant_id": tenant_id}

        Indexer(db).rebuild_tenant(tenant_id=tid, kinds=[IndexKind.CHUNK])
        elapsed = time.perf_counter() - t0
        return {"ok": True, "elapsed_sec": round(elapsed, 3)}
    finally:
        if redis is not None and lock_key and lock_val:
            await release_lock(redis, key=lock_key, value=lock_val)
        await tenant_release(redis, sem_key)
        db.close()
