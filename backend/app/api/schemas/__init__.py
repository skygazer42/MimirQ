"""
API 请求/响应数据模型

定义 API 接口的 Pydantic 验证模型和内部服务使用的数据类。
"""

# 导出索引相关的定义
from app.api.schemas.indexing import (
    ChunkInput,
    EventEntityInput,
    EventInput,
    IndexBatchResult,
    IndexKind,
    IndexingOptions,
    IndexRecord,
    PersistChunksResult,
    PersistEventsResult,
)

# 导出流水线相关的定义
from app.api.schemas.pipeline import (
    PipelineEffective,
    PipelineOptions,
)

__all__ = [
    # 索引相关
    "ChunkInput",
    "EventEntityInput",
    "EventInput",
    "IndexBatchResult",
    "IndexKind",
    "IndexingOptions",
    "IndexRecord",
    "PersistChunksResult",
    "PersistEventsResult",
    # 流水线相关
    "PipelineEffective",
    "PipelineOptions",
]

