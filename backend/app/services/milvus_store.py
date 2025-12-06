"""
Milvus 向量数据库服务
"""
from typing import List, Dict, Any, Optional
from langchain_openai import OpenAIEmbeddings
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

from app.config import settings

# 延迟导入 sentence_transformers（仅在需要时导入）
try:
    from sentence_transformers import SentenceTransformer
    SENTENCE_TRANSFORMERS_AVAILABLE = True
except ImportError:
    SENTENCE_TRANSFORMERS_AVAILABLE = False


class MilvusVectorStore:
    """Milvus 向量存储服务"""

    _instance = None
    _embedding_model = None
    _embedding_provider = None
    _collection = None
    _embedding_dim = 1024  # BGE-large 的维度

    def __new__(cls):
        """单例模式"""
        if cls._instance is None:
            cls._instance = super(MilvusVectorStore, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        """初始化 Milvus 连接和 Collection"""
        if self._embedding_model is None:
            self._embedding_provider = (settings.EMBEDDING_PROVIDER or "local").lower()
            self._embedding_model = self._init_embedding_model()
            self._embedding_dim = self._get_embedding_dimension()
            print(f"[OK] Embedding dimension: {self._embedding_dim}")

        if self._collection is None:
            self._connect_milvus()
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
            print(f"📱 Using device: {device}")

            return SentenceTransformer(
                settings.EMBEDDING_MODEL,
                device=device
            )

        if provider in {"openai_compatible", "openai"}:
            return OpenAIEmbeddings(
                model=settings.EMBEDDING_MODEL,
                api_key=settings.EMBEDDING_API_KEY or settings.LLM_API_KEY,
                base_url=settings.EMBEDDING_API_BASE or settings.LLM_API_BASE
            )

        raise ValueError(f"Unsupported EMBEDDING_PROVIDER: {provider}")

    def _get_embedding_dimension(self) -> int:
        """探测 embedding 维度"""
        test_vector = self._embed_query("ping")
        return len(test_vector)

    def _connect_milvus(self):
        """连接到 Milvus 服务器"""
        print(f"🔌 Connecting to Milvus at {settings.MILVUS_HOST}:{settings.MILVUS_PORT}")

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
            print(f"📂 Loading existing collection: {collection_name}")
            self._collection = Collection(collection_name)
            self._collection.load()
        else:
            print(f"📦 Creating new collection: {collection_name}")

            # 定义 Schema
            fields = [
                FieldSchema(name="id", dtype=DataType.VARCHAR, is_primary=True, max_length=100),
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
        return self._embedding_model

    @property
    def collection(self):
        """获取 Milvus Collection"""
        return self._collection

    def add_documents(
        self,
        documents: List[Dict[str, Any]],
        document_id: UUID
    ) -> List[str]:
        """
        添加文档到 Milvus

        Args:
            documents: 文档列表，每个包含 content 和 metadata
            document_id: 文档 ID

        Returns:
            插入的向量 ID 列表
        """
        if not documents:
            return []

        # 准备数据
        ids = []
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
            doc_ids.append(str(document_id))
            chunk_indices.append(metadata.get('chunk_index', idx))
            contents.append(content[:65535])  # Milvus VARCHAR 限制
            page_numbers.append(metadata.get('page', 0))
            sources.append(metadata.get('source', 'unknown')[:500])
            file_types.append(metadata.get('file_type', 'unknown')[:20])

        # 批量生成 Embeddings
        print(f"🔢 Generating embeddings for {len(contents)} chunks...")
        embeddings = self._embed_documents(contents)

        # 插入数据
        data = [
            ids,
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
        document_ids: Optional[List[UUID]] = None
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

        # 执行搜索
        results = self._collection.search(
            data=[query_embedding],
            anns_field="embedding",
            param=search_params,
            limit=top_k * 2,  # 多检索一些，然后过滤
            expr=expr,
            output_fields=["document_id", "content", "page_number", "source", "chunk_index"]
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

    def delete_by_document_id(self, document_id: UUID) -> None:
        """
        删除指定文档的所有向量

        Args:
            document_id: 文档 ID
        """
        expr = f'document_id == "{str(document_id)}"'
        self._collection.delete(expr)
        self._collection.flush()
        print(f"🗑️  Deleted vectors for document: {document_id}")

    def get_collection_count(self) -> int:
        """获取向量库中的文档数量"""
        self._collection.flush()
        return self._collection.num_entities


# 全局实例
milvus_store = MilvusVectorStore()
