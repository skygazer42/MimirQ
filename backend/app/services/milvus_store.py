"""
Milvus 向量数据库服务

Notes:
- Avoid heavy initialization at import time. The vector store now lazily
  initializes embeddings and Milvus connections on first use so the FastAPI
  app can start even when external services are not ready.
"""
from __future__ import annotations

from typing import List, Dict, Any, Optional

import os
import httpx
from pymilvus import (
    connections,
    Collection,
    CollectionSchema,
    FieldSchema,
    DataType,
    utility
)
from uuid import UUID
import numpy as np

from app.core.config import settings

# 延迟导入 sentence_transformers（仅在需要时导入）
try:
    from sentence_transformers import SentenceTransformer
    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False


class DashScopeEmbeddings:
    """阿里云 DashScope Embedding 封装"""

    def __init__(self, model: str, api_key: str):
        self.model = model
        self.api_key = api_key
        try:
            import dashscope
            dashscope.api_key = api_key
            self._dashscope = dashscope
        except ImportError:
            raise ImportError(
                "DashScope SDK not found. Please install: pip install dashscope"
            )

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        """批量生成文档向量"""
        from dashscope import TextEmbedding

        embeddings = []
        # DashScope 批量限制为 25 条
        batch_size = 25
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            response = TextEmbedding.call(
                model=self.model,
                input=batch
            )
            if response.status_code == 200:
                for item in response.output['embeddings']:
                    embeddings.append(item['embedding'])
            else:
                raise Exception(f"DashScope API error: {response.code} - {response.message}")
        return embeddings

    def embed_query(self, text: str) -> List[float]:
        """生成查询向量"""
        result = self.embed_documents([text])
        return result[0] if result else []


class OpenAICompatEmbeddings:
    """Minimal embeddings client using the official OpenAI SDK.

    This is a fallback when `langchain_openai` is unavailable or incompatible.
    It exposes the same `embed_documents`/`embed_query` surface we rely on.
    """

    def __init__(self, model: str, api_key: str, base_url: str, timeout: int = 60, trust_env: bool = True):
        self.model = model
        from openai import OpenAI

        http_client = httpx.Client(trust_env=trust_env, timeout=timeout)
        self._client = OpenAI(api_key=api_key, base_url=base_url, http_client=http_client)

    def embed_documents(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        resp = self._client.embeddings.create(model=self.model, input=texts)
        return [item.embedding for item in resp.data]

    def embed_query(self, text: str) -> List[float]:
        vectors = self.embed_documents([text])
        return vectors[0] if vectors else []


class MilvusVectorStore:
    """Milvus 向量存储服务"""

    _instance = None
    _embedding_model = None
    _embedding_provider = None
    _collection = None
    _embedding_dim: Optional[int] = None  # lazily detected

    def __new__(cls):
        """单例模式"""
        if cls._instance is None:
            cls._instance = super(MilvusVectorStore, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        """Lightweight init. Real setup happens on first use."""
        if self._embedding_provider is None:
            self._embedding_provider = (settings.EMBEDDING_PROVIDER or "local").lower()

    def _ensure_embedding_model(self):
        """Make sure embedding client and dimension are ready."""
        if self._embedding_model is None:
            self._embedding_provider = (settings.EMBEDDING_PROVIDER or "local").lower()
            self._embedding_model = self._init_embedding_model()

        # Dimension is only needed when creating a new collection.
        if self._embedding_dim is None and self._collection is None:
            try:
                self._embedding_dim = self._get_embedding_dimension()
                print(f"[OK] Embedding dimension: {self._embedding_dim}")
            except Exception as exc:
                raise RuntimeError(f"Failed to detect embedding dimension: {exc}") from exc

    def _ensure_collection(self):
        """Ensure Milvus connection + collection are initialized."""
        if self._collection is not None:
            return

        # Try to load existing collection without forcing a remote embedding call.
        self._connect_milvus()
        collection_name = settings.MILVUS_COLLECTION_NAME
        if utility.has_collection(collection_name):
            print(f"[Milvus] Loading existing collection: {collection_name}")
            self._collection = Collection(collection_name)
            try:
                embedding_field = next(
                    f for f in self._collection.schema.fields if f.name == "embedding"
                )
                dim = getattr(embedding_field, "dim", None) or embedding_field.params.get("dim")
                if dim:
                    self._embedding_dim = int(dim)
            except Exception:
                pass
            self._collection.load()
            return

        # Collection doesn't exist, need embedding dimension to create it.
        self._ensure_embedding_model()
        self._init_collection()

    def _init_embedding_model(self):
        """初始化 Embedding 客户端"""
        provider = self._embedding_provider
        print(f"[*] Loading embedding provider: {provider}")

        if provider == "local":
            if not SENTENCE_TRANSFORMERS_AVAILABLE:
                raise ImportError(
                    "本地 Embedding 模型需要安装额外依赖。\n"
                    "请运行: pip install -r requirements-local.txt\n"
                    "或者改用 API 方式: EMBEDDING_PROVIDER=openai_compatible"
                )

            # 自动检测设备：优先使用 GPU，如果没有则使用 CPU
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"
            print(f"[Device] Using: {device}")

            return SentenceTransformer(
                settings.EMBEDDING_MODEL,
                device=device
            )

        if provider == "dashscope":
            # 阿里云 DashScope 专用
            return DashScopeEmbeddings(
                model=settings.EMBEDDING_MODEL,
                api_key=settings.EMBEDDING_API_KEY or settings.LLM_API_KEY
            )

        if provider in {"openai_compatible", "openai"}:
            # LangChain's OpenAI clients read proxy env vars by default.
            # SOCKS proxies are not supported and would crash validation, so
            # we disable env proxies in that case.
            proxy_candidates = [
                os.getenv("OPENAI_PROXY"),
                os.getenv("HTTPS_PROXY"),
                os.getenv("HTTP_PROXY"),
                os.getenv("ALL_PROXY"),
            ]
            proxy = next((p for p in proxy_candidates if p), None)
            trust_env = True
            if proxy and proxy.lower().startswith("socks"):
                print(f"[WARN] Unsupported SOCKS proxy for embeddings detected: {proxy}. Ignoring env proxies.")
                trust_env = False
                proxy = None

            http_client = httpx.Client(trust_env=trust_env)
            http_async_client = httpx.AsyncClient(trust_env=trust_env)

            api_key = settings.EMBEDDING_API_KEY or settings.LLM_API_KEY
            base_url = settings.EMBEDDING_API_BASE or settings.LLM_API_BASE

            try:
                from langchain_openai import OpenAIEmbeddings as LCOpenAIEmbeddings
            except Exception as exc:
                print(f"[WARN] langchain_openai embeddings unavailable: {exc}. Falling back to OpenAI SDK.")
                return OpenAICompatEmbeddings(
                    model=settings.EMBEDDING_MODEL,
                    api_key=api_key,
                    base_url=base_url,
                    timeout=settings.LLM_TIMEOUT,
                    trust_env=trust_env,
                )

            return LCOpenAIEmbeddings(
                model=settings.EMBEDDING_MODEL,
                api_key=api_key,
                base_url=base_url,
                openai_proxy=proxy,
                http_client=http_client,
                http_async_client=http_async_client,
            )

        raise ValueError(f"Unsupported EMBEDDING_PROVIDER: {provider}")

    def _get_embedding_dimension(self) -> int:
        """探测 embedding 维度"""
        test_vector = self._embed_query("ping")
        return len(test_vector)

    def _connect_milvus(self):
        """连接到 Milvus 服务器"""
        print(f"[Milvus] Connecting to {settings.MILVUS_HOST}:{settings.MILVUS_PORT}")

        connections.connect(
            alias="default",
            host=settings.MILVUS_HOST,
            port=settings.MILVUS_PORT,
            user=settings.MILVUS_USER,
            password=settings.MILVUS_PASSWORD
        )

        print("[OK] Connected to Milvus")

    def _init_collection(self):
        """初始化或加载 Collection"""
        collection_name = settings.MILVUS_COLLECTION_NAME

        # 检查 Collection 是否存在
        if utility.has_collection(collection_name):
            print(f"[Milvus] Loading existing collection: {collection_name}")
            self._collection = Collection(collection_name)
            self._collection.load()
        else:
            print(f"[Milvus] Creating new collection: {collection_name}")

            # 定义 Schema
            fields = [
                FieldSchema(name="id", dtype=DataType.VARCHAR, is_primary=True, max_length=100),
                FieldSchema(name="tenant_id", dtype=DataType.VARCHAR, max_length=100),
                FieldSchema(name="document_id", dtype=DataType.VARCHAR, max_length=100),
                FieldSchema(name="chunk_index", dtype=DataType.INT64),
                FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=65535),
                FieldSchema(name="page_number", dtype=DataType.INT64),
                FieldSchema(name="source", dtype=DataType.VARCHAR, max_length=500),
                FieldSchema(name="file_type", dtype=DataType.VARCHAR, max_length=20),
                FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=self._embedding_dim)
            ]

            schema = CollectionSchema(
                fields=fields,
                description="Document chunks with embeddings"
            )

            # 创建 Collection
            self._collection = Collection(
                name=collection_name,
                schema=schema
            )

            # 创建索引
            index_params = {
                "metric_type": "COSINE",  # 余弦相似度
                "index_type": "IVF_FLAT",
                "params": {"nlist": 1024}
            }

            self._collection.create_index(
                field_name="embedding",
                index_params=index_params
            )

            # 加载 Collection 到内存
            self._collection.load()

            print(f"[OK] Collection created and indexed")

    def _embed_documents(self, texts: List[str]) -> List[List[float]]:
        """根据配置生成文档向量"""
        if not texts:
            return []

        if self._embedding_provider == "local":
            return self._embedding_model.encode(
                texts,
                normalize_embeddings=True,
                show_progress_bar=True
            ).tolist()

        embeddings = self._embedding_model.embed_documents(texts)
        return self._normalize_embeddings(embeddings)

    def _embed_query(self, query: str) -> List[float]:
        """生成查询向量"""
        if self._embedding_provider == "local":
            return self._embedding_model.encode(
                [query],
                normalize_embeddings=True
            )[0].tolist()

        embedding = self._embedding_model.embed_query(query)
        return self._normalize_embeddings([embedding])[0]

    @staticmethod
    def _normalize_embeddings(vectors: List[List[float]]) -> List[List[float]]:
        """对嵌入结果进行归一化以匹配 COSINE 相似度检索"""
        array = np.array(vectors, dtype=float)
        norms = np.linalg.norm(array, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        normalized = array / norms
        return normalized.tolist()

    @property
    def embedding_model(self):
        """获取 Embedding 模型"""
        self._ensure_embedding_model()
        return self._embedding_model

    @property
    def collection(self):
        """获取 Milvus Collection"""
        self._ensure_collection()
        return self._collection

    def add_documents(
        self,
        documents: List[Dict[str, Any]],
        document_id: UUID,
        tenant_id: UUID
    ) -> List[str]:
        """
        添加文档到 Milvus

        Args:
            documents: 文档列表，每个包含 content 和 metadata
            document_id: 文档 ID

        Returns:
            插入的向量 ID 列表
        """
        self._ensure_collection()
        if not documents:
            return []

        # 准备数据
        ids = []
        tenant_ids = []
        doc_ids = []
        chunk_indices = []
        contents = []
        page_numbers = []
        sources = []
        file_types = []
        embeddings = []

        for idx, doc in enumerate(documents):
            content = doc.get('content', '')
            metadata = doc.get('metadata', {})

            # 生成唯一 ID
            vector_id = f"{document_id}_{idx}"

            ids.append(vector_id)
            tenant_ids.append(str(tenant_id))
            doc_ids.append(str(document_id))
            chunk_indices.append(metadata.get('chunk_index', idx))
            contents.append(content[:65535])  # Milvus VARCHAR 限制
            page_numbers.append(metadata.get('page', 0))
            sources.append(metadata.get('source', 'unknown')[:500])
            file_types.append(metadata.get('file_type', 'unknown')[:20])

        # 批量生成 Embeddings
        print(f"[Embedding] Generating embeddings for {len(contents)} chunks...")
        self._ensure_embedding_model()
        embeddings = self._embed_documents(contents)

        # 插入数据
        data = [
            ids,
            tenant_ids,
            doc_ids,
            chunk_indices,
            contents,
            page_numbers,
            sources,
            file_types,
            embeddings
        ]

        print(f"[*] Inserting {len(ids)} vectors into Milvus...")
        self._collection.insert(data)
        self._collection.flush()

        print(f"[OK] Inserted {len(ids)} vectors")
        return ids

    def search(
        self,
        query: str,
        top_k: int = 5,
        score_threshold: float = 0.7,
        document_ids: Optional[List[UUID]] = None,
        tenant_id: Optional[UUID] = None
    ) -> List[Dict[str, Any]]:
        """
        检索相似文档

        Args:
            query: 查询文本
            top_k: 返回 Top-K 结果
            score_threshold: 相似度阈值 (0-1)
            document_ids: 限定在指定文档范围内搜索

        Returns:
            检索结果列表
        """
        self._ensure_collection()
        self._ensure_embedding_model()
        # 生成查询向量
        query_embedding = self._embed_query(query)

        # 构建搜索参数
        search_params = {
            "metric_type": "COSINE",
            "params": {"nprobe": 10}
        }

        # 构建过滤表达式
        expr = None
        if document_ids:
            doc_id_strs = [f'"{str(doc_id)}"' for doc_id in document_ids]
            expr = f"document_id in [{', '.join(doc_id_strs)}]"
        if tenant_id:
            tenant_expr = f'tenant_id == "{str(tenant_id)}"'
            expr = f"{tenant_expr}" if not expr else f"{tenant_expr} and {expr}"

        # 执行搜索
        results = self._collection.search(
            data=[query_embedding],
            anns_field="embedding",
            param=search_params,
            limit=top_k * 2,  # 多检索一些，然后过滤
            expr=expr,
            output_fields=["tenant_id", "document_id", "content", "page_number", "source", "chunk_index"]
        )

        # 格式化结果
        formatted_results = []
        for hits in results:
            for hit in hits:
                # Milvus 的 distance 是余弦相似度，范围 0-1（越大越相似）
                score = hit.distance

                # 过滤低于阈值的结果
                if score < score_threshold:
                    continue

                formatted_results.append({
                    "content": hit.entity.get("content"),
                    "metadata": {
                        "document_id": hit.entity.get("document_id"),
                        "source": hit.entity.get("source"),
                        "page": hit.entity.get("page_number"),
                        "chunk_index": hit.entity.get("chunk_index"),
                        "score": float(score)
                    },
                    "score": float(score)
                })

                # 达到 top_k 就停止
                if len(formatted_results) >= top_k:
                    break

            if len(formatted_results) >= top_k:
                break

        return formatted_results

    def delete_by_document_id(self, document_id: UUID, tenant_id: Optional[UUID] = None) -> None:
        """
        删除指定文档的所有向量

        Args:
            document_id: 文档 ID
        """
        self._ensure_collection()
        expr_parts = [f'document_id == "{str(document_id)}"']
        if tenant_id:
            expr_parts.append(f'tenant_id == "{str(tenant_id)}"')
        expr = " and ".join(expr_parts)
        self._collection.delete(expr)
        self._collection.flush()
        print(f"[Milvus] Deleted vectors for document: {document_id}")

    def get_collection_count(self) -> int:
        """获取向量库中的文档数量"""
        self._ensure_collection()
        self._collection.flush()
        return self._collection.num_entities


# 全局实例
milvus_store = MilvusVectorStore()
