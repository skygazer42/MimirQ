"""
存储模块

提供向量存储、对象存储、混合检索等功能。

主要组件：
- vector: 向量数据库（Milvus、FAISS、Chroma）
- object: 对象存储（MinIO）
- search: 混合检索（BM25 + 向量）
"""

# 向量存储
from app.storage.vector.factory import get_vector_store
from app.storage.vector.milvus import milvus_store

# 对象存储
from app.storage.object.minio import minio_service

# 混合检索
from app.storage.search.hybrid_retriever import hybrid_retriever

__all__ = [
    # 向量存储
    'get_vector_store',
    'milvus_store',
    # 对象存储
    'minio_service',
    # 检索
    'hybrid_retriever',
]




