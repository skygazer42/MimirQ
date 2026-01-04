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

logger = get_logger("tasks.jobs")


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
        db.close()


