"""
Vector storage backends.

Exports:
- MilvusVectorStore: Singleton for document vectors
- MilvusAdapter: Multi-instance adapter for custom collections (KG)
- get_milvus_adapter: Cached adapter factory for custom collections
- get_vector_store: Factory function from factory.py
"""
from app.storage.vector.milvus import MilvusVectorStore, MilvusAdapter, get_milvus_adapter, milvus_store
from app.storage.vector.factory import get_vector_store

__all__ = [
    "MilvusVectorStore",
    "MilvusAdapter",
    "get_milvus_adapter",
    "milvus_store",
    "get_vector_store",
]
