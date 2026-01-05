"""
队列任务实现（worker 执行侧）。

注意：
- 任务执行必须二次校验 tenant/document 归属，避免多租户越权。
- 任务幂等锁/缓存将在后续 todo 中完善；这里先提供最小可运行骨架。
"""

from __future__ import annotations

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
    简易 per-tenant 并发限制（Redis 计数信号量）。
    - INCR 后若 > limit，则回滚 DECR 并触发延迟重试。
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
                raise Retry(defer=2)  # 2s 后重试（arq 会继续递增 try）
            # 无 Retry 时直接返回 None（不阻塞）
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
    文档处理任务：解析→切块→索引。

    Args:
        tenant_id: tenant UUID string
        document_id: document UUID string
        requested_by: account_id（仅用于审计/日志）
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
        # 任务执行必须二次校验 tenant/document 归属
        doc = (
            db.query(DBDocument)
            .filter(DBDocument.id == did, DBDocument.tenant_id == tid)
            .first()
        )
        if not doc:
            # 任务可视为完成（目标资源不存在）
            return {"ok": False, "reason": "document_not_found", "tenant_id": tenant_id, "document_id": document_id}

        pipeline_hash = (doc.doc_metadata or {}).get("pipeline_hash") or "unknown"
        lock_key = f"lock:doc:{tenant_id}:{document_id}:{pipeline_hash}"

        # 幂等锁：避免同一文档+同一pipeline被重复并发处理
        # - 使用 Redis SET NX EX
        # - lock 超时略大于 job_timeout，防止 worker 崩溃导致永久锁
        try:
            redis = ctx.get("redis") if isinstance(ctx, dict) else None
        except Exception:  # noqa: BLE001
            redis = None

        lock_val = f"{requested_by}:{int(time.time())}"
        lock_ttl = 60 * 40  # 40 min
        if redis is not None:
            # per-tenant 并发限制（doc）
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

        # 二次校验通过：执行文档处理
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
    KG 抽取任务：从已完成的 chunks 中抽取 events/entities 并写入索引。
    """
    from app.models.document import DocumentChunk
    from app.rag.kg.pipeline import extract_events
    from app.services.pipeline_config import build_indexing_options, resolve_pipeline_options
    from app.parsing.processors.processor import parse_pipeline_from_metadata

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
            # 未完成则稍后重试（通常是 ingest 还在跑）
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

        pipeline_options = parse_pipeline_from_metadata(doc.doc_metadata or {})
        effective = resolve_pipeline_options(pipeline_options)
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
    重建索引任务（当前用于 BM25 重建；后续可扩展向量/其他）。
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


