from __future__ import annotations

from app.storage.vector.qdrant import QdrantVectorStore


class PGVectorStore(QdrantVectorStore):
    """Deterministic in-process PGVector scaffold reusing the Qdrant-style interface."""
