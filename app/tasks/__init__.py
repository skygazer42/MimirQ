"""
Background task system (queue + Redis).

Used for ingest throughput optimizations:
- After document upload: enqueue processing (parsing/chunking/embeddings/indexing)
- Redis: idempotency locks, cache, status (optional)
"""

from app.tasks.queue import enqueue_document_processing, get_queue, init_queue, close_queue

__all__ = [
    "enqueue_document_processing",
    "get_queue",
    "init_queue",
    "close_queue",
]

