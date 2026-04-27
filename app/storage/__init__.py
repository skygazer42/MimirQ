"""
Storage module

Provides vector storage and object storage functionality.

Main components:
- vector: Vector databases (Milvus, FAISS, Chroma)
- object: Object storage (MinIO)

Note: Hybrid retrieval has been moved to app.rag.retriever module.
"""


from typing import Any

__all__ = ["get_vector_store", "milvus_store", "minio_service", "get_object_store"]


def __getattr__(name: str) -> Any:
    """
    Lazy exports to avoid importing heavy dependencies at package import time.

    Import submodules directly when possible:
    - from app.storage.vector.factory import get_vector_store
    - from app.storage.vector.milvus import milvus_store
    - from app.storage.object.minio import minio_service
    """
    if name == "get_vector_store":
        from app.storage.vector.factory import get_vector_store

        return get_vector_store
    if name == "milvus_store":
        from app.storage.vector.milvus import milvus_store

        return milvus_store
    if name == "minio_service":
        from app.storage.object.minio import minio_service

        return minio_service
    if name == "get_object_store":
        from app.storage.object.factory import get_object_store

        return get_object_store
    raise AttributeError(f"module 'app.storage' has no attribute {name!r}")







