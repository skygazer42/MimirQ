"""
Vector storage backends.

Exports:
- MilvusVectorStore: Singleton for document vectors
- MilvusAdapter: Multi-instance adapter for custom collections (SAG)
- get_vector_store: Factory function from factory.py
"""
from app.storage.vector.milvus import MilvusVectorStore, MilvusAdapter, milvus_store
from app.storage.vector.factory import get_vector_store

__all__ = [
    "MilvusVectorStore",
    "MilvusAdapter",
    "milvus_store",
    "get_vector_store",
]
