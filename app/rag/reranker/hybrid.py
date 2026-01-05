"""
Hybrid Reranker（混合重排器）

融合向量相似度和关键词匹配的混合重排策略。

实现：
- 向量检索：基于语义相似度
- 关键词检索：基于 TF-IDF
- 加权融合：可配置权重组合两种分数
"""
from __future__ import annotations

import math
from collections import Counter
from enum import Enum
from typing import Callable

from pydantic import BaseModel

from app.models.chunk import Document
from app.rag.reranker.base import DocumentReranker


class RerankMode(str, Enum):
    """Rerank mode enumeration."""

    RERANKING_MODEL = "reranking_model"
    WEIGHTED_SCORE = "weighted_score"
    PARENT_CHILD = "parent_child"


class VectorSetting(BaseModel):
    """Vector weight settings."""

    vector_weight: float
    embedding_provider_name: str
    embedding_model_name: str


class KeywordSetting(BaseModel):
    """Keyword weight settings."""

    keyword_weight: float


class Weights(BaseModel):
    """Model for weighted rerank combining vector and keyword scores."""

    vector_setting: VectorSetting
    keyword_setting: KeywordSetting


class WeightedReranker(DocumentReranker):
    """加权重排器：融合向量相似度和关键词匹配"""

    def __init__(
        self,
        tenant_id: str,
        weights: Weights,
        embedding_fn: Callable[[str], list[float]] | None = None,
    ):
        """
        初始化加权重排器

        Args:
            tenant_id: 租户标识
            weights: 向量和关键词权重配置
            embedding_fn: 可选的 embedding 生成函数
        """
        self.tenant_id = tenant_id
        self.weights = weights
        self.embedding_fn = embedding_fn

    def run(
        self,
        query: str,
        documents: list[Document],
        score_threshold: float | None = None,
        top_n: int | None = None,
        user: str | None = None,
    ) -> list[Document]:
        """运行加权重排"""
        # 去重
        unique_documents: list[Document] = []
        doc_ids: set[str] = set()
        for document in documents:
            meta = document.metadata or {}
            doc_id = meta.get("doc_id") or meta.get("document_id")
            if doc_id is not None:
                key = str(doc_id)
                if key in doc_ids:
                    continue
                doc_ids.add(key)
                unique_documents.append(document)
            else:
                if document not in unique_documents:
                    unique_documents.append(document)

        documents = unique_documents

        # 计算分数
        query_scores = self._calculate_keyword_score(query, documents)
        query_vector_scores = self._calculate_cosine(query, documents, self.weights.vector_setting)

        # 融合分数
        rerank_documents = []
        for document, query_score, query_vector_score in zip(documents, query_scores, query_vector_scores):
            score = (
                self.weights.vector_setting.vector_weight * query_vector_score
                + self.weights.keyword_setting.keyword_weight * query_score
            )
            if score_threshold and score < score_threshold:
                continue
            if document.metadata is not None:
                document.metadata["score"] = score
                rerank_documents.append(document)

        rerank_documents.sort(key=lambda x: x.metadata.get("score", 0) if x.metadata else 0, reverse=True)
        return rerank_documents[:top_n] if top_n else rerank_documents

    def _calculate_keyword_score(self, query: str, documents: list[Document]) -> list[float]:
        """计算基于 TF-IDF 的关键词相似度分数"""
        from app.rag.preprocessing.keyword import JiebaKeywordTableHandler

        keyword_table_handler = JiebaKeywordTableHandler()
        query_keywords = keyword_table_handler.extract_keywords(query, None)
        documents_keywords = []

        for document in documents:
            document_keywords = keyword_table_handler.extract_keywords(document.page_content, None)
            if document.metadata is not None:
                document.metadata["keywords"] = document_keywords
            documents_keywords.append(document_keywords)

        # Counter query keywords (TF)
        query_keyword_counts = Counter(query_keywords)

        # Total documents
        total_documents = len(documents)

        # Calculate IDF for all keywords
        all_keywords = set()
        for document_keywords in documents_keywords:
            all_keywords.update(document_keywords)

        keyword_idf = {}
        for keyword in all_keywords:
            doc_count_containing_keyword = sum(1 for doc_keywords in documents_keywords if keyword in doc_keywords)
            keyword_idf[keyword] = math.log((1 + total_documents) / (1 + doc_count_containing_keyword)) + 1

        # Query TF-IDF
        query_tfidf = {}
        for keyword, count in query_keyword_counts.items():
            tf = count
            idf = keyword_idf.get(keyword, 0)
            query_tfidf[keyword] = tf * idf

        # Documents TF-IDF
        documents_tfidf = []
        for document_keywords in documents_keywords:
            document_keyword_counts = Counter(document_keywords)
            document_tfidf = {}
            for keyword, count in document_keyword_counts.items():
                tf = count
                idf = keyword_idf.get(keyword, 0)
                document_tfidf[keyword] = tf * idf
            documents_tfidf.append(document_tfidf)

        def cosine_similarity(vec1: dict, vec2: dict) -> float:
            intersection = set(vec1.keys()) & set(vec2.keys())
            numerator = sum(vec1[x] * vec2[x] for x in intersection)

            sum1 = sum(vec1[x] ** 2 for x in vec1)
            sum2 = sum(vec2[x] ** 2 for x in vec2)
            denominator = math.sqrt(sum1) * math.sqrt(sum2)

            if not denominator:
                return 0.0
            return float(numerator) / denominator

        similarities = []
        for document_tfidf in documents_tfidf:
            similarity = cosine_similarity(query_tfidf, document_tfidf)
            similarities.append(similarity)

        return similarities

    def _calculate_cosine(
        self, query: str, documents: list[Document], vector_setting: VectorSetting
    ) -> list[float]:
        """使用 embeddings 计算余弦相似度分数"""
        query_vector_scores = []

        # 获取 query 向量
        if self.embedding_fn:
            query_vector = self.embedding_fn(query)
        else:
            # 如果没有 embedding 函数，返回现有分数
            for document in documents:
                if document.metadata and "score" in document.metadata:
                    query_vector_scores.append(document.metadata["score"])
                else:
                    query_vector_scores.append(0.0)
            return query_vector_scores

        for document in documents:
            if document.metadata and "score" in document.metadata:
                query_vector_scores.append(document.metadata["score"])
            elif document.vector:
                import numpy as np

                vec1 = np.array(query_vector)
                vec2 = np.array(document.vector)

                dot_product = np.dot(vec1, vec2)
                norm_vec1 = np.linalg.norm(vec1)
                norm_vec2 = np.linalg.norm(vec2)

                cosine_sim = dot_product / (norm_vec1 * norm_vec2) if norm_vec1 and norm_vec2 else 0.0
                query_vector_scores.append(float(cosine_sim))
            else:
                query_vector_scores.append(0.0)

        return query_vector_scores
