"""
兼容模块：索引相关内部类型（已迁移）

说明：
- 这些类型属于内部服务编排用，不应放在 API schema 层
- 为兼容旧引用，保留该模块并转发到 `app.types.indexing`
"""

from app.types.indexing import (  # noqa: F401
    ChunkInput,
    EventEntityInput,
    EventInput,
    IndexBatchResult,
    IndexKind,
    IndexingOptions,
    IndexRecord,
    IndexScope,
    PersistChunksResult,
    PersistEventsResult,
)


__all__ = [
    "ChunkInput",
    "EventEntityInput",
    "EventInput",
    "IndexBatchResult",
    "IndexKind",
    "IndexingOptions",
    "IndexRecord",
    "IndexScope",
    "PersistChunksResult",
    "PersistEventsResult",
]




