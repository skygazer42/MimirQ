"""
Milvus 向量库服务（LangChain 1.x API 管理）

本模块将 Milvus 的 collection/索引/搜索交给 LangChain 的
`langchain_community.vectorstores.Milvus` 管理，同时保留项目原有的
`add_documents/search/delete_by_document_id/get_collection_count` 接口，
避免影响上层业务。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID
import os
import logging

import httpx
import numpy as np

from app.core.config import settings

logger = logging.getLogger(__name__)


# ========= Embeddings Providers =========

try:
    from sentence_transformers import SentenceTransformer
    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:  # pragma: no cover
    SENTENCE_TRANSFORMERS_AVAILABLE = False


def _normalize_embeddings(vectors: List[List[float]]) -> List[List[float]]:
    array = np.array(vectors, dtype=float)
    norms = np.linalg.norm(array, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (array / norms).tolist()


class LocalEmbeddings:
    """SentenceTransformer embeddings adapter."""

    def __init__(self, model_name: str):
        if not SENTENCE_TRANSFORMERS_AVAILABLE:
            raise ImportError(
                "本地 Embedding 模型需要安装额外依赖。\n"
                "请运行: pip install -r requirements-local.txt\n"
                "或者改用 API 方式: EMBEDDING_PROVIDER=openai_compatible"
            )

        import torch  # local 模式下要求已安装 torch

        device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info("[Device] Using %s for embeddings", device)
        self._model = SentenceTransformer(model_name, device=device)

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        return (
            self._model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
            .tolist()
        )

    def embed_query(self, text: str) -> List[float]:
        return self.embed_documents([text])[0]


class DashScopeEmbeddings:
    """阿里云 DashScope Embedding 封装（返回归一化向量）"""

    def __init__(self, model: str, api_key: str):
        self.model = model
        try:
            import dashscope

            dashscope.api_key = api_key
            self._dashscope = dashscope
        except ImportError as exc:  # pragma: no cover
            raise ImportError("DashScope SDK not found. Please install: pip install dashscope") from exc

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        from dashscope import TextEmbedding

        embeddings: List[List[float]] = []
        batch_size = 25
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            response = TextEmbedding.call(model=self.model, input=batch)
            if response.status_code != 200:
                raise RuntimeError(f"DashScope API error: {response.code} - {response.message}")
            for item in response.output["embeddings"]:
                embeddings.append(item["embedding"])
        return _normalize_embeddings(embeddings)

    def embed_query(self, text: str) -> List[float]:
        return self.embed_documents([text])[0]


class OpenAICompatEmbeddings:
    """Minimal embeddings client using the official OpenAI SDK (normalized)."""

    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: str,
        timeout: int = 60,
        trust_env: bool = True,
    ):
        from openai import OpenAI

        http_client = httpx.Client(trust_env=trust_env, timeout=timeout)
        self.model = model
        self._client = OpenAI(api_key=api_key, base_url=base_url, http_client=http_client)

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        resp = self._client.embeddings.create(model=self.model, input=texts)
        vectors = [item.embedding for item in resp.data]
        return _normalize_embeddings(vectors)

    def embed_query(self, text: str) -> List[float]:
        return self.embed_documents([text])[0]


# ========= Milvus Store (LangChain-managed) =========


class MilvusVectorStore:
    """Milvus 向量存储服务（对外接口保持不变）"""

    _instance: Optional["MilvusVectorStore"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        self._embedding_provider = (settings.EMBEDDING_PROVIDER or "local").lower()
        self._embedding_model = None
        self._store = None  # langchain_community.vectorstores.Milvus

    def _init_embedding_model(self):
        provider = self._embedding_provider
        logger.info("[*] Loading embedding provider: %s", provider)

        if provider == "local":
            return LocalEmbeddings(settings.EMBEDDING_MODEL)

        if provider == "dashscope":
            return DashScopeEmbeddings(
                model=settings.EMBEDDING_MODEL,
                api_key=settings.EMBEDDING_API_KEY or settings.LLM_API_KEY,
            )

        if provider in {"openai_compatible", "openai"}:
            proxy_candidates = [
                os.getenv("OPENAI_PROXY"),
                os.getenv("HTTPS_PROXY"),
                os.getenv("HTTP_PROXY"),
                os.getenv("ALL_PROXY"),
            ]
            proxy = next((p for p in proxy_candidates if p), None)
            trust_env = True
            if proxy and proxy.lower().startswith("socks"):
                logger.warning("Unsupported SOCKS proxy for embeddings: %s. Ignoring env proxies.", proxy)
                trust_env = False

            api_key = settings.EMBEDDING_API_KEY or settings.LLM_API_KEY
            base_url = settings.EMBEDDING_API_BASE or settings.LLM_API_BASE
            return OpenAICompatEmbeddings(
                model=settings.EMBEDDING_MODEL,
                api_key=api_key,
                base_url=base_url,
                timeout=settings.LLM_TIMEOUT,
                trust_env=trust_env,
            )

        raise ValueError(f"Unsupported EMBEDDING_PROVIDER: {provider}")

    def _ensure_store(self):
        if self._store is not None:
            return

        if self._embedding_model is None:
            self._embedding_model = self._init_embedding_model()

        from langchain_community.vectorstores import Milvus as LCMilvus

        connection_args = {
            "host": settings.MILVUS_HOST,
            "port": str(settings.MILVUS_PORT),
            "user": settings.MILVUS_USER,
            "password": settings.MILVUS_PASSWORD,
        }

        index_params = {
            "metric_type": "COSINE",
            "index_type": "IVF_FLAT",
            "params": {"nlist": 1024},
        }
        search_params = {"metric_type": "COSINE", "params": {"nprobe": 10}}

        # 使用项目已有 schema: id/content/embedding + tenant_id/document_id 等标量字段
        self._store = LCMilvus(
            embedding_function=self._embedding_model,
            collection_name=settings.MILVUS_COLLECTION_NAME,
            connection_args=connection_args,
            index_params=index_params,
            search_params=search_params,
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
        expr_parts: List[str] = []
        if tenant_id:
            expr_parts.append(f'tenant_id == "{str(tenant_id)}"')
        if document_ids:
            doc_id_strs = [f'"{str(doc_id)}"' for doc_id in document_ids]
            expr_parts.append(f"document_id in [{', '.join(doc_id_strs)}]")
        return " and ".join(expr_parts) if expr_parts else None

    # -------- Public API --------

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
        """向量相似度检索"""
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


# 全局实例（懒初始化）
milvus_store = MilvusVectorStore()

