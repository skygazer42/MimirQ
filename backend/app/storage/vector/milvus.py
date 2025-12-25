"""
Milvus 向量库服务（LangChain 1.x API 管理）



提供两种使用模式：
1. 单例模式 - 用于文档向量存储（固定 collection）
2. 多实例模式 - 用于 SAG 实体/事件（可自定义 collection）
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID
import logging

from app.core.config import settings
from app.rag.embedding import create_langchain_embeddings_from_config

logger = logging.getLogger(__name__)


# ========= Embedding 初始化 (共享) ==========

def _init_embedding_model():
    """Initialize embedding model using app.rag.embedding module."""
    provider = (settings.EMBEDDING_PROVIDER or "local").lower()
    logger.info("[*] Loading embedding provider: %s", provider)

    provider_map = {
        "openai": "openai_compatible",
        "openai_compatible": "openai_compatible",
        "local": "local",
        "dashscope": "dashscope",
    }

    mapped_provider = provider_map.get(provider, "openai_compatible")
    api_key = settings.EMBEDDING_API_KEY or settings.LLM_API_KEY
    base_url = settings.EMBEDDING_API_BASE or settings.LLM_API_BASE

    return create_langchain_embeddings_from_config(
        provider=mapped_provider,
        model=settings.EMBEDDING_MODEL,
        api_key=api_key or "",
        base_url=base_url or "",
        dimension=None,  # Auto-detect
    )


def _get_milvus_connection_args() -> Dict[str, Any]:
    """获取 Milvus 连接配置."""
    return {
        "host": settings.MILVUS_HOST,
        "port": str(settings.MILVUS_PORT),
        "user": settings.MILVUS_USER,
        "password": settings.MILVUS_PASSWORD,
    }


def _get_milvus_index_params() -> Dict[str, Any]:
    """获取 Milvus 索引配置."""
    return {
        "metric_type": "COSINE",
        "index_type": "IVF_FLAT",
        "params": {"nlist": 1024},
    }


def _get_milvus_search_params() -> Dict[str, Any]:
    """获取 Milvus 搜索配置."""
    return {"metric_type": "COSINE", "params": {"nprobe": 10}}


# ========= 通用 Milvus 适配器 ==========

class MilvusAdapter:
    """
    通用 Milvus 适配器，支持自定义 collection。

    用于 SAG 实体/事件向量存储，支持多 collection。
    """

    def __init__(
        self,
        collection_name: str,
        vector_field: str = "embedding",
        text_field: str = "content",
    ):
        self.collection_name = collection_name
        self.vector_field = vector_field
        self.text_field = text_field
        self._store = None
        self._embedding_model = None

    def _ensure_store(self):
        if self._store is not None:
            return

        if self._embedding_model is None:
            self._embedding_model = _init_embedding_model()

        from langchain_community.vectorstores import Milvus as LCMilvus

        self._store = LCMilvus(
            embedding_function=self._embedding_model,
            collection_name=self.collection_name,
            connection_args=_get_milvus_connection_args(),
            index_params=_get_milvus_index_params(),
            search_params=_get_milvus_search_params(),
            auto_id=False,
            primary_field="id",
            text_field=self.text_field,
            vector_field=self.vector_field,
        )

    def add_vectors(
        self,
        items: List[Dict[str, Any]],
        embeddings: Optional[List[List[float]]] = None,
        *,
        batch_size: int = 1000,
        timeout: Optional[float] = None,
        upsert: bool = True,
        **kwargs: Any,
    ) -> List[str]:
        """
        批量写入向量（支持直接写入预计算 embeddings，避免重复 embedding）。

        Args:
            items: [{"id": str, "content": str, "metadata": dict}]
            embeddings: 可选，预计算向量（List[List[float]]），与 items 一一对应。
                - 为 None 时：由 LangChain Embeddings 根据 content 自动生成
                - 不为 None 时：直接写入 Milvus（insert/upsert）
            batch_size: 写入 batch size
            timeout: Milvus timeout
            upsert: True 使用 Milvus upsert；False 使用 insert

        Returns:
            向量 ID 列表
        """
        if not items:
            return []

        self._ensure_store()
        assert self._store is not None

        reserved_fields = {
            getattr(self._store, "_primary_field", "id"),
            getattr(self._store, "_text_field", self.text_field),
            getattr(self._store, "_vector_field", self.vector_field),
        }

        texts: List[str] = []
        metadatas: List[Dict[str, Any]] = []
        ids: List[str] = []
        for item in items:
            ids.append(str(item["id"]))
            texts.append((item.get("content") or "")[:65_000])
            meta = dict(item.get("metadata") or {})
            for key in reserved_fields:
                meta.pop(key, None)
            metadatas.append(meta)

        # Default path: let LangChain generate embeddings then insert.
        if embeddings is None:
            pks = self._store.add_texts(
                texts=texts,
                metadatas=metadatas,
                ids=ids,
                batch_size=batch_size,
                timeout=timeout,
                **kwargs,
            )
            return [str(pk) for pk in pks]

        if len(embeddings) != len(items):
            raise ValueError("embeddings length must match items length")

        from pymilvus import Collection, MilvusException

        # Ensure collection initialized (schema/index/search params/load).
        if not isinstance(getattr(self._store, "col", None), Collection):
            init_kwargs: Dict[str, Any] = {"embeddings": embeddings, "metadatas": metadatas}
            partition_names = getattr(self._store, "partition_names", None)
            if partition_names:
                init_kwargs["partition_names"] = partition_names
            replica_number = getattr(self._store, "replica_number", None)
            if replica_number:
                init_kwargs["replica_number"] = replica_number
            store_timeout = getattr(self._store, "timeout", None)
            if store_timeout:
                init_kwargs["timeout"] = store_timeout
            # `_init` is the internal LangChain helper used by `add_texts`.
            self._store._init(**init_kwargs)  # type: ignore[attr-defined]

        # Build insert columns (match LangChain Milvus.insert behavior).
        insert_dict: Dict[str, List[Any]] = {
            self._store._text_field: texts,  # type: ignore[attr-defined]
            self._store._vector_field: embeddings,  # type: ignore[attr-defined]
        }
        if not getattr(self._store, "auto_id", False):
            insert_dict[self._store._primary_field] = ids  # type: ignore[attr-defined]

        metadata_field = getattr(self._store, "_metadata_field", None)
        if metadata_field is not None:
            insert_dict[metadata_field] = metadatas
        else:
            fields = getattr(self._store, "fields", [])
            for d in metadatas:
                for key, value in d.items():
                    keys = (
                        [x for x in fields if x != self._store._primary_field]  # type: ignore[attr-defined]
                        if getattr(self._store, "auto_id", False)
                        else [x for x in fields]
                    )
                    if key in keys:
                        insert_dict.setdefault(key, []).append(value)

        total_count = len(embeddings)
        pks: List[str] = []
        assert isinstance(self._store.col, Collection)
        for i in range(0, total_count, batch_size):
            end = min(i + batch_size, total_count)
            insert_list = [insert_dict[x][i:end] for x in self._store.fields if x in insert_dict]
            try:
                eff_timeout = getattr(self._store, "timeout", None) or timeout
                if upsert:
                    res = self._store.col.upsert(insert_list, timeout=eff_timeout, **kwargs)
                    pks.extend([str(pk) for pk in res.primary_keys])
                else:
                    res = self._store.col.insert(insert_list, timeout=eff_timeout, **kwargs)
                    pks.extend([str(pk) for pk in res.primary_keys])
            except MilvusException as e:
                logger.error("Failed to write vectors batch: %s/%s", i, total_count)
                raise e

        return pks

    def delete(self, ids: List[str]) -> None:
        """删除指定 ID 的向量。"""
        if not ids:
            return
        self._ensure_store()
        assert self._store is not None
        self._store.delete(ids)

    def search(
        self,
        query_vector: List[float],
        top_k: int = 10,
        expr: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        向量相似度搜索。

        Args:
            query_vector: 查询向量
            top_k: 返回结果数量
            expr: 过滤表达式

        Returns:
            搜索结果列表
        """
        self._ensure_store()
        assert self._store is not None

        results = self._store.similarity_search_with_score_by_vector(
            embedding=query_vector,
            k=top_k,
            expr=expr,
        )
        return [
            {
                "id": doc.id,
                "metadata": doc.metadata or {},
                "score": float(score),
                "content": doc.page_content,
            }
            for doc, score in results
        ]


# ========= 文档向量存储 (单例) ==========

class MilvusVectorStore:
    """
    Milvus 向量存储服务（文档向量专用，单例模式）。

    用于知识库文档的向量存储，使用固定的 collection 名称。
    """

    _instance: Optional["MilvusVectorStore"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        self._embedding_provider = (settings.EMBEDDING_PROVIDER or "local").lower()
        self._embedding_model = None
        self._store = None

    def _init_embedding_model(self):
        """Initialize embedding model (用于 sag_milvus 兼容)."""
        return _init_embedding_model()

    def _ensure_store(self):
        if self._store is not None:
            return

        if self._embedding_model is None:
            self._embedding_model = _init_embedding_model()

        from langchain_community.vectorstores import Milvus as LCMilvus

        self._store = LCMilvus(
            embedding_function=self._embedding_model,
            collection_name=settings.MILVUS_COLLECTION_NAME,
            connection_args=_get_milvus_connection_args(),
            index_params=_get_milvus_index_params(),
            search_params=_get_milvus_search_params(),
            auto_id=False,
            primary_field="id",
            text_field="content",
            vector_field="embedding",
        )

    def _build_expr(
        self,
        document_ids: Optional[List[UUID]] = None,
        tenant_id: Optional[UUID] = None,
    ) -> Optional[str]:
        """构建 Milvus 过滤表达式。"""
        expr_parts: List[str] = []
        if tenant_id:
            expr_parts.append(f'tenant_id == "{str(tenant_id)}"')
        if document_ids:
            doc_id_strs = [f'"{str(doc_id)}"' for doc_id in document_ids]
            expr_parts.append(f"document_id in [{', '.join(doc_id_strs)}]")
        return " and ".join(expr_parts) if expr_parts else None

    def add_documents(
        self,
        documents: List[Dict[str, Any]],
        document_id: UUID,
        tenant_id: UUID,
    ) -> List[str]:
        """添加文档 chunks 到 Milvus（返回向量 id 列表）"""
        self._ensure_store()
        assert self._store is not None

        texts: List[str] = []
        metadatas: List[Dict[str, Any]] = []
        ids: List[str] = []

        for idx, doc in enumerate(documents):
            content = (doc.get("content") or "")[:65_535]
            meta = doc.get("metadata") or {}

            vector_id = f"{document_id}_{idx}"
            ids.append(vector_id)
            texts.append(content)

            metadatas.append(
                {
                    "tenant_id": str(tenant_id),
                    "document_id": str(document_id),
                    "chunk_index": int(meta.get("chunk_index", idx)),
                    "page_number": int(meta.get("page") or meta.get("page_number") or 0),
                    "source": str(meta.get("source", "unknown"))[:500],
                    "file_type": str(meta.get("file_type", "unknown"))[:20],
                }
            )

        pks = self._store.add_texts(texts=texts, metadatas=metadatas, ids=ids)
        return [str(pk) for pk in pks]

    def search(
        self,
        query: str,
        top_k: int = 5,
        score_threshold: float = 0.7,
        document_ids: Optional[List[UUID]] = None,
        tenant_id: Optional[UUID] = None,
    ) -> List[Dict[str, Any]]:
        """向量相似度检索（使用文本查询）"""
        self._ensure_store()
        assert self._store is not None

        expr = self._build_expr(document_ids=document_ids, tenant_id=tenant_id)
        results = self._store.similarity_search_with_score(query, k=top_k * 2, expr=expr)

        formatted: List[Dict[str, Any]] = []
        for doc, score in results:
            if score < score_threshold:
                continue
            meta = doc.metadata or {}
            formatted.append(
                {
                    "content": doc.page_content,
                    "metadata": {
                        "tenant_id": meta.get("tenant_id"),
                        "document_id": meta.get("document_id"),
                        "source": meta.get("source", "unknown"),
                        "page": meta.get("page_number"),
                        "chunk_index": meta.get("chunk_index"),
                        "score": float(score),
                    },
                    "score": float(score),
                }
            )
            if len(formatted) >= top_k:
                break

        return formatted

    def delete_by_document_id(self, document_id: UUID, tenant_id: Optional[UUID] = None) -> None:
        """删除指定文档的所有向量"""
        self._ensure_store()
        assert self._store is not None

        expr = self._build_expr(document_ids=[document_id], tenant_id=tenant_id)
        if expr:
            self._store.delete(expr=expr)
            try:
                self._store.col.flush()  # type: ignore[union-attr]
            except Exception:
                pass

    def get_collection_count(self) -> int:
        """获取向量库中的文档数量"""
        self._ensure_store()
        assert self._store is not None
        try:
            return int(self._store.col.num_entities)  # type: ignore[union-attr]
        except Exception:
            return 0


# ========= 全局实例 ==========

# 文档向量存储（单例）
milvus_store = MilvusVectorStore()
