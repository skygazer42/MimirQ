"""
存储模块

提供向量存储、对象存储、混合检索等功能。

主要组件：
- vector: 向量数据库（Milvus、FAISS、Chroma）
- object: 对象存储（MinIO）
- search: 混合检索（BM25 + 向量）
"""

from __future__ import annotations

from typing import Any

__all__ = ["get_vector_store", "milvus_store", "minio_service", "hybrid_retriever"]


def __getattr__(name: str) -> Any:  # pragma: no cover
    """
    Lazy exports to avoid importing heavy dependencies at package import time.

    Import submodules directly when possible:
    - from app.storage.vector.factory import get_vector_store
    - from app.storage.vector.milvus import milvus_store
    - from app.storage.object.minio import minio_service
    - from app.storage.search.hybrid_retriever import hybrid_retriever
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
    if name == "hybrid_retriever":
        from app.storage.search.hybrid_retriever import hybrid_retriever

        return hybrid_retriever
    raise AttributeError(f"module 'app.storage' has no attribute {name!r}")



