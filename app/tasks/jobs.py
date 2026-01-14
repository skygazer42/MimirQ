"""
Queue job implementations (worker side).

Notes:
- Jobs must re-validate tenant/document ownership to avoid cross-tenant access.
- Jobs use best-effort Redis locks/semaphores to avoid duplicate work.
"""


import time
from pathlib import Path
from uuid import UUID

from app.core.database import SessionLocal
from app.models.document import Document as DBDocument
from app.parsing.processors.processor import document_processor
from app.rag.core.logging import get_logger
from app.core.config import settings
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
        file_path = Path(doc.file_path)

        logger.info(
            "Processing document job: tenant_id=%s document_id=%s requested_by=%s",
            tenant_id,
            document_id,
            requested_by,
        )

        result = await document_processor.process_document(
            file_path=file_path,
            document_id=did,
            tenant_id=tid,
            parser_backend=parser_backend,
            chunk_strategy=chunk_strategy,
            db=db,
        )
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
    from app.models.document import DocumentChunk
    from app.models.dataset import Dataset
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
            Retry = get_retry_exc()
            if Retry:
                raise Retry(defer=5)
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
