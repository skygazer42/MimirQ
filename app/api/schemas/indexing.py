"""
Compatibility module: Indexing-related internal types (migrated)

Notes:
- These types are for internal service orchestration, not for API schema layer
- Kept for backward compatibility, forwarding to `app.types.indexing`
"""

from app.types.indexing import (  # noqa: F401
    ChunkInput,
    EventEntityInput,
    EventInput,
    IndexBatchResult,
    IndexingOptions,
    IndexKind,
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




