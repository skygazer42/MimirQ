"""
后台任务系统（队列 + Redis）

当前用于 ingest 吞吐优化：
- 文档上传后：入队处理（解析/切块/embedding/索引）
- Redis：任务幂等锁、缓存、状态（可选）
"""

from app.tasks.queue import enqueue_document_processing, get_queue, init_queue, close_queue

__all__ = [
    "enqueue_document_processing",
    "get_queue",
    "init_queue",
    "close_queue",
]


