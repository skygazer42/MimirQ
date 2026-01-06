"""
Milvus 向量库服务

提供两种使用模式：
1. 单例模式 - 用于文档向量存储（固定 collection）
2. 多实例模式 - 用于 KG 实体/事件（可自定义 collection）
"""
from __future__ import annotations

import logging
import threading
import re
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from app.core.config import settings
from app.core.constants import MilvusConfig, EmbeddingProviders
from app.rag.core.filters import match_metadata_filter as _match_metadata_filter

logger = logging.getLogger(__name__)

_MILVUS_MAX_VARCHAR_BYTES = 65_535
_MILVUS_EXPR_MAX_CHARS = 8000
_MILVUS_FIELD_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Safe allowlist for metadata expr pushdown (must exist in collection schema).
_MILVUS_NUMERIC_FIELDS = frozenset({"chunk_index", "page_number"})
_MILVUS_STRING_FIELDS = frozenset(
    {
        "tenant_id",
        "document_id",
        "chunk_id",
        "source",
        "file_type",
        "img_id",
        "image_id",
        "image_url",
        # KG (optional; depends on collection schema)
        "index_kind",
        "type",
        "name",
        "title",
    }
)
_MILVUS_ALLOWED_FILTER_FIELDS = _MILVUS_NUMERIC_FIELDS | _MILVUS_STRING_FIELDS


def _coerce_milvus_metadata_value(value: Any) -> Any:
    """Milvus does not support None values for scalar fields."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return bool(value)
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        return float(value)
    if isinstance(value, str):
        return value[:_MILVUS_MAX_VARCHAR_BYTES]
    return str(value)[:_MILVUS_MAX_VARCHAR_BYTES]


def _normalize_milvus_metadata_batch(metadatas: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Ensure consistent keys and Milvus-compatible values across a batch."""
    if not metadatas:
        return metadatas

    schema_meta: Dict[str, Any] = {}
    for k, v in (metadatas[0] or {}).items():
        schema_meta[str(k)] = _coerce_milvus_metadata_value(v)

    schema_keys = list(schema_meta.keys())
    for meta in metadatas:
        # Normalize values for known keys first.
        for k in list(meta.keys()):
            meta[k] = _coerce_milvus_metadata_value(meta.get(k))

        # Fill missing schema keys so insert columns remain aligned.
        for k in schema_keys:
            if k in meta and meta[k] != "":
                continue
            exemplar = schema_meta.get(k)
            if isinstance(exemplar, bool):
                meta[k] = False
            elif isinstance(exemplar, int):
                meta[k] = 0
            elif isinstance(exemplar, float):
                meta[k] = 0.0
            else:
                meta[k] = ""

    return metadatas


def _escape_milvus_string(value: str) -> str:
    # Milvus expr strings use double quotes; escape minimal set.
    return value.replace("\\", "\\\\").replace('"', '\\"')


def _milvus_value_expr(field: str, value: Any) -> Optional[str]:
    if field in _MILVUS_NUMERIC_FIELDS:
        try:
            return str(int(value))
        except Exception:
            return None
    if field in _MILVUS_STRING_FIELDS:
        return f"\"{_escape_milvus_string(str(value))}\""
    return None


def _milvus_in_list_expr(field: str, values: Any) -> Optional[str]:
    if not isinstance(values, (list, tuple, set)):
        return None
    items: List[str] = []
    for v in values:
        expr = _milvus_value_expr(field, v)
        if expr is None:
            continue
        items.append(expr)
    if not items:
        return None
    return f"[{', '.join(items)}]"


def _build_milvus_metadata_expr(metadata_filter: Optional[Dict[str, Any]]) -> Optional[str]:
    """Best-effort translation of metadata_filter into Milvus expr (AND semantics)."""
    if not metadata_filter or not isinstance(metadata_filter, dict):
        return None

    parts: List[str] = []
    for key, condition in metadata_filter.items():
        if not isinstance(key, str):
            continue
        if key not in _MILVUS_ALLOWED_FILTER_FIELDS:
            continue
        if not _MILVUS_FIELD_NAME_RE.match(key):
            continue

        if isinstance(condition, dict):
            for op, expected in condition.items():
                if op in ("$eq", "$ne"):
                    rhs = _milvus_value_expr(key, expected)
                    if rhs is None:
                        continue
                    parts.append(f"{key} {'==' if op == '$eq' else '!='} {rhs}")
                elif op in ("$gt", "$gte", "$lt", "$lte"):
                    if key not in _MILVUS_NUMERIC_FIELDS:
                        continue
                    rhs = _milvus_value_expr(key, expected)
                    if rhs is None:
                        continue
                    cmp_op = {  # noqa: RUF027
                        "$gt": ">",
                        "$gte": ">=",
                        "$lt": "<",
                        "$lte": "<=",
                    }.get(op)
                    if cmp_op:
                        parts.append(f"{key} {cmp_op} {rhs}")
                elif op in ("$in", "$nin"):
                    rhs = _milvus_in_list_expr(key, expected)
                    if rhs is None:
                        continue
                    parts.append(f"{key} {'in' if op == '$in' else 'not in'} {rhs}")
                else:
                    # Unsupported op (e.g. $contains): skip pushdown for this clause.
                    continue
        else:
            rhs = _milvus_value_expr(key, condition)
            if rhs is None:
                continue
            parts.append(f"{key} == {rhs}")

    if not parts:
        return None
    expr = " and ".join(parts)
    if len(expr) > _MILVUS_EXPR_MAX_CHARS:
        return None
    return expr


# ========= Embedding 初始化 ==========

def _init_embedding_model():
    """Initialize embedding model using app.rag.embedding module."""
    from app.rag.embedding import create_langchain_embeddings_from_config

    provider = (settings.EMBEDDING_PROVIDER or "local").lower()
    logger.info("[*] Loading embedding provider: %s", provider)

    mapped_provider = EmbeddingProviders.PROVIDER_MAP.get(provider, "openai_compatible")
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
    return MilvusConfig.get_index_params()


def _get_milvus_search_params() -> Dict[str, Any]:
    """获取 Milvus 搜索配置."""
    return MilvusConfig.get_search_params()


# ========= 通用 Milvus 适配器 ==========

class MilvusAdapter:
    """
    通用 Milvus 适配器，支持自定义 collection。

    用于 KG 实体/事件向量存储，支持多 collection。
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
        metadatas = _normalize_milvus_metadata_batch(metadatas)

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
            except MilvusException:
                logger.exception(
                    "Failed to write vectors batch: %s/%s collection=%s",
                    i,
                    total_count,
                    self.collection_name,
                )
                raise

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
        metadata_filter: Optional[Dict[str, Any]] = None,
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

        metadata_expr = _build_milvus_metadata_expr(metadata_filter)
        if expr and metadata_expr:
            combined_expr = f"({expr}) and ({metadata_expr})"
        else:
            combined_expr = expr or metadata_expr

        try:
            results = self._store.similarity_search_with_score_by_vector(
                embedding=query_vector,
                k=top_k,
                expr=combined_expr,
            )
        except Exception:
            # Fallback: ignore pushdown on schema/expr mismatch; still apply client-side filtering.
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
            if not metadata_filter or _match_metadata_filter(doc.metadata or {}, metadata_filter)
        ]


_milvus_adapter_cache: Dict[Tuple[str, str, str], MilvusAdapter] = {}
_milvus_adapter_cache_lock = threading.Lock()


def resolve_collection_name(preferred: str) -> str:
    """Resolve canonical Milvus collection name."""
    return preferred


def get_milvus_adapter(
    collection_name: str,
    *,
    vector_field: str = "embedding",
    text_field: str = "content",
) -> MilvusAdapter:
    key = (collection_name, vector_field, text_field)
    with _milvus_adapter_cache_lock:
        cached = _milvus_adapter_cache.get(key)
        if cached is not None:
            return cached
        adapter = MilvusAdapter(collection_name=collection_name, vector_field=vector_field, text_field=text_field)
        _milvus_adapter_cache[key] = adapter
        return adapter


# ========= 文档向量存储 (单例) ==========

class MilvusVectorStore:
    """
    Milvus 向量存储服务（文档向量专用，单例模式）。

    用于知识库文档的向量存储，使用固定的 collection 名称。
    """

    _instance: Optional["MilvusVectorStore"] = None
    _lock: threading.Lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                # Double-check locking pattern
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        self._embedding_provider = (settings.EMBEDDING_PROVIDER or "local").lower()
        self._embedding_model = None
        self._store = None

    def _init_embedding_model(self):
        """Initialize embedding model."""
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

            # Prefer stable chunk_id (UUID string) when available to avoid collisions on re-index.
            chunk_id = meta.get("chunk_id")
            vector_id = str(chunk_id) if chunk_id else f"{document_id}_{idx}"
            ids.append(vector_id)
            texts.append(content)

            img_id = meta.get("img_id") or meta.get("image_id") or ""
            image_id = meta.get("image_id") or meta.get("img_id") or ""
            image_url = meta.get("image_url") or meta.get("img_url") or ""

            metadatas.append(
                {
                    "tenant_id": str(tenant_id),
                    "document_id": str(document_id),
                    "chunk_index": int(meta.get("chunk_index", idx)),
                    "chunk_id": str(chunk_id) if chunk_id else "",
                    "page_number": int(meta.get("page") or meta.get("page_number") or 0),
                    "source": str(meta.get("source", "unknown"))[:500],
                    "file_type": str(meta.get("file_type", "unknown"))[:20],
                    "img_id": str(img_id)[:500],
                    "image_id": str(image_id)[:500],
                    "image_url": str(image_url)[:2000],
                }
            )

        metadatas = _normalize_milvus_metadata_batch(metadatas)
        pks = self._store.add_texts(texts=texts, metadatas=metadatas, ids=ids)
        return [str(pk) for pk in pks]

    def search(
        self,
        query: str,
        top_k: int = 5,
        score_threshold: float = 0.7,
        document_ids: Optional[List[UUID]] = None,
        tenant_id: Optional[UUID] = None,
        metadata_filter: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """向量相似度检索（使用文本查询）"""
        self._ensure_store()
        assert self._store is not None

        base_expr = self._build_expr(document_ids=document_ids, tenant_id=tenant_id)
        metadata_expr = _build_milvus_metadata_expr(metadata_filter)
        if base_expr and metadata_expr:
            combined_expr = f"({base_expr}) and ({metadata_expr})"
        else:
            combined_expr = base_expr or metadata_expr

        try:
            results = self._store.similarity_search_with_score(query, k=top_k * 2, expr=combined_expr)
        except Exception:
            # Fallback for legacy collections / unsupported expr clauses.
            results = self._store.similarity_search_with_score(query, k=top_k * 2, expr=base_expr)

        formatted: List[Dict[str, Any]] = []
        for doc, score in results:
            if score < score_threshold:
                continue
            meta = doc.metadata or {}
            if metadata_filter and not _match_metadata_filter(meta, metadata_filter):
                continue
            chunk_id = meta.get("chunk_id")
            formatted.append(
                {
                    "chunk_id": chunk_id,
                    "content": doc.page_content,
                    "metadata": {
                        "tenant_id": meta.get("tenant_id"),
                        "document_id": meta.get("document_id"),
                        "source": meta.get("source", "unknown"),
                        "page": meta.get("page_number"),
                        "chunk_index": meta.get("chunk_index"),
                        "chunk_id": chunk_id,
                        "img_id": meta.get("img_id") or meta.get("image_id"),
                        "image_id": meta.get("image_id") or meta.get("img_id"),
                        "image_url": meta.get("image_url") or meta.get("img_url"),
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
