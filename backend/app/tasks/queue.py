"""
API 侧队列操作：初始化队列连接、enqueue 文档处理任务。

保持 API 兼容：
- 若 TASK_QUEUE_ENABLED=false，则上层仍可使用 BackgroundTasks 走原有路径。
"""

from __future__ import annotations

import asyncio
from typing import Optional, Any
from uuid import UUID

from app.core.config import settings
from app.rag.core.logging import get_logger

logger = get_logger("tasks.queue")

# arq 是可选依赖：当 TASK_QUEUE_ENABLED=false 时，不应要求安装 arq
_queue: Optional[Any] = None
_queue_lock = asyncio.Lock()


def _redis_settings():
    # arq 的 RedisSettings 支持传入完整 DSN
    from arq.connections import RedisSettings

    return RedisSettings.from_dsn(settings.REDIS_URL)


async def init_queue() -> None:
    """在应用启动时初始化队列连接（可选）。"""
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
    """在应用关闭时关闭队列连接。"""
    global _queue
    if _queue is None:
        return
    try:
        await _queue.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Failed to close task queue: %s", str(exc)[:200])
    finally:
        _queue = None


async def get_queue() -> Optional[Any]:
    """获取队列连接（懒加载）。"""
    if not bool(getattr(settings, "TASK_QUEUE_ENABLED", False)):
        return None
    if _queue is None:
        await init_queue()
    return _queue


async def enqueue_document_processing(
    *,
    tenant_id: UUID,
    document_id: UUID,
    requested_by: str,
    job_id: Optional[str] = None,
) -> Optional[str]:
    """
    入队“文档处理”任务。

    Returns:
        - task_id/job_id（队列开启时）
        - None（队列未开启）
    """
    q = await get_queue()
    if q is None:
        return None

    queue_name = getattr(settings, "TASK_QUEUE_NAME", "mimirq")
    # Arq 的 job_id 可用于去重（同一个 job_id 会覆盖/拒绝取决于 arq 行为版本），
    # 我们仍会在任务执行侧做 Redis 锁保证幂等。
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


