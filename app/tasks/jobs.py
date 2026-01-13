"""
Queue job implementations (worker side).

Notes:
- Jobs must re-validate tenant/document ownership to avoid cross-tenant access.
- Idempotent locks/cache are TODO; this provides a minimal runnable skeleton.
"""


import time
from pathlib import Path
from uuid import UUID

from app.core.database import SessionLocal
from app.models.document import Document as DBDocument
from app.parsing.processors.processor import document_processor
from app.rag.core.logging import get_logger
from app.core.config import settings

logger = get_logger("tasks.jobs")

def _get_retry_exc():
    try:
        from arq import Retry  # type: ignore

        return Retry
    except Exception:  # noqa: BLE001
        return None


async def _tenant_acquire(redis, *, tenant_id: str, kind: str, limit: int, ttl_sec: int = 120):  # noqa: ANN001
    """
    Simple per-tenant concurrency limit (Redis counting semaphore).
    - If INCR > limit, roll back with DECR and trigger a delayed retry.
    """
    if redis is None or limit <= 0:
        return None
    key = f"sem:tenant:{tenant_id}:{kind}"
    try:
        val = await redis.incr(key)
        await redis.expire(key, ttl_sec)
        if int(val) > int(limit):
            await redis.decr(key)
            Retry = _get_retry_exc()
            if Retry:
                raise Retry(defer=2)  # Retry after 2s (arq increments try).
            # Return None if Retry is unavailable (non-blocking).
            return None
        return key
    except Exception as exc:  # noqa: BLE001
        logger.warning("Tenant semaphore acquire failed (skip limit): %s", str(exc)[:200])
        return None


async def _tenant_release(redis, key: str | None):  # noqa: ANN001
    if redis is None or not key:
        return
    try:
        val = await redis.decr(key)
        if int(val) <= 0:
            await redis.delete(key)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Tenant semaphore release failed: %s", str(exc)[:200])


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

        lock_val = f"{requested_by}:{int(time.time())}"
        lock_ttl = 60 * 40  # 40 min
        if redis is not None:
            # Per-tenant concurrency limit (doc).
            sem_key = await _tenant_acquire(
                redis,
                tenant_id=tenant_id,
                kind="doc",
                limit=int(getattr(settings, "TASK_TENANT_MAX_CONCURRENCY_DOC", 0) or 0),
                ttl_sec=120,
            )
            try:
                acquired = await redis.set(lock_key, lock_val, ex=lock_ttl, nx=True)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Redis lock acquire failed (continue without lock): %s", str(exc)[:200])
                acquired = True
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
            try:
                cur = await redis.get(lock_key)
                cur_decoded = cur.decode("utf-8", "ignore") if isinstance(cur, (bytes, bytearray)) else cur
                if cur_decoded == lock_val:
                    await redis.delete(lock_key)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Redis lock release failed: %s", str(exc)[:200])
        if redis is not None:
            await _tenant_release(redis, sem_key)
        db.close()


async def extract_kg_job(ctx, tenant_id: str, document_id: str, requested_by: str) -> dict:  # noqa: ANN001
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
    try:
        try:
            redis = ctx.get("redis") if isinstance(ctx, dict) else None
        except Exception:  # noqa: BLE001
            redis = None

        if redis is not None:
            sem_key = await _tenant_acquire(
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
            Retry = _get_retry_exc()
            if Retry:
                raise Retry(defer=5)
            return {"ok": False, "reason": "document_not_completed", "status": doc.status}

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
        )
        elapsed = time.perf_counter() - t0
        return {"ok": True, "event_count": len(events), "elapsed_sec": round(elapsed, 3)}
    finally:
        if redis is not None:
            await _tenant_release(redis, sem_key)
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
    try:
        try:
            redis = ctx.get("redis") if isinstance(ctx, dict) else None
        except Exception:  # noqa: BLE001
            redis = None

        if redis is not None:
            sem_key = await _tenant_acquire(
                redis,
                tenant_id=tenant_id,
                kind="rebuild",
                limit=int(getattr(settings, "TASK_TENANT_MAX_CONCURRENCY_DOC", 0) or 0),
                ttl_sec=120,
            )

        Indexer(db).rebuild_tenant(tenant_id=tid, kinds=[IndexKind.CHUNK])
        elapsed = time.perf_counter() - t0
        return {"ok": True, "elapsed_sec": round(elapsed, 3)}
    finally:
        if redis is not None:
            await _tenant_release(redis, sem_key)
        db.close()
