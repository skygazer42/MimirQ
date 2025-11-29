"""
向量数据库服务 (ChromaDB)
"""
from typing import List, Dict, Any, Optional
from uuid import UUID

from langchain_community.vectorstores import Chroma
from langchain_community.embeddings import HuggingFaceEmbeddings
from langchain_core.documents import Document

from app.config import settings


class VectorStoreService:
    """向量存储服务 (基于 ChromaDB)"""

    _instance = None
    _embedding_model = None
    _vectorstore = None

    def __new__(cls):
        """单例模式，确保只初始化一次"""
        if cls._instance is None:
            cls._instance = super(VectorStoreService, cls).__new__(cls)
        return cls._instance

    def __init__(self):
        """初始化 Embedding 模型和向量数据库"""
        if self._embedding_model is None:
            print(f"Loading embedding model: {settings.EMBEDDING_MODEL}")
            self._embedding_model = HuggingFaceEmbeddings(
                model_name=settings.EMBEDDING_MODEL,
                model_kwargs={"device": settings.EMBEDDING_DEVICE},
                encode_kwargs={"normalize_embeddings": True},
            )

        if self._vectorstore is None:
            print(f"Initializing ChromaDB at: {settings.CHROMA_PERSIST_DIR}")
            self._vectorstore = Chroma(
                embedding_function=self._embedding_model,
                persist_directory=settings.CHROMA_PERSIST_DIR,
                collection_name="documents",
            )

    @property
    def embedding_model(self):
        """获取 Embedding 模型"""
        return self._embedding_model

    @property
    def vectorstore(self):
        """获取向量数据库实例"""
        return self._vectorstore

    async def add_documents(
        self, documents: List[Document], document_id: UUID
    ) -> List[str]:
        """
        添加文档到向量库

        Args:
            documents: LangChain Document 列表
            document_id: 文档 ID

        Returns:
            新增向量的 ID 列表
        """
        # 为每个 chunk 添加 document_id 元数据
        for doc in documents:
            doc.metadata["document_id"] = str(document_id)

        # 批量写入 Chroma
        ids = await self._vectorstore.aadd_documents(documents)
        return ids

    async def search(
        self,
        query: str,
        top_k: int = 5,
        score_threshold: float = 0.7,
        document_ids: Optional[List[UUID]] = None,
    ) -> List[Dict[str, Any]]:
        """
        检索相似文档

        Args:
            query: 查询文本
            top_k: 返回 Top-K 结果
            score_threshold: 相似度阈值
            document_ids: 只在指定文档范围内检索

        Returns:
            检索结果列表
        """
        # 构造过滤条件
        filter_dict = None
        if document_ids:
            filter_dict = {
                "document_id": {"$in": [str(doc_id) for doc_id in document_ids]}
            }

        # 相似度检索
        results = await self._vectorstore.asimilarity_search_with_relevance_scores(
            query,
            k=top_k,
            score_threshold=score_threshold,
            filter=filter_dict,
        )

        # 格式化结果
        formatted_results: List[Dict[str, Any]] = []
        for doc, score in results:
            formatted_results.append(
                {
                    "content": doc.page_content,
                    "metadata": doc.metadata,
                    "score": score,
                }
            )

        return formatted_results

    async def delete_by_document_id(self, document_id: UUID) -> None:
        """
        删除指定文档的所有向量

        Args:
            document_id: 文档 ID
        """
        # ChromaDB 使用 where 条件删除
        self._vectorstore._collection.delete(where={"document_id": str(document_id)})

    def get_collection_count(self) -> int:
        """获取向量库中的文档数量"""
        return self._vectorstore._collection.count()


# 全局实例
vector_store_service = VectorStoreService()
