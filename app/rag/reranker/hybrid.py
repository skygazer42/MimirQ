"""
Hybrid reranker.

Combines vector similarity and keyword matching for reranking.

Implementation:
- Vector retrieval: semantic similarity
- Keyword retrieval: TF-IDF
- Weighted fusion: configurable weights for both scores
"""

import math
from collections import Counter
from collections.abc import Callable
from enum import Enum

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
    """Weighted reranker combining vector similarity and keyword matching."""

    def __init__(
        self,
        tenant_id: str,
        weights: Weights,
        embedding_fn: Callable[[str], list[float]] | None = None,
    ):
        """
        Initialize the weighted reranker.

        Args:
            tenant_id: tenant identifier
            weights: vector and keyword weight configuration
            embedding_fn: optional embedding function
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
        """Run weighted reranking."""
        # Deduplicate.
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

        # Compute scores.
        query_scores = self._calculate_keyword_score(query, documents)
        query_vector_scores = self._calculate_cosine(query, documents, self.weights.vector_setting)

        # Fuse scores.
        rerank_documents = []
        for document, query_score, query_vector_score in zip(documents, query_scores, query_vector_scores, strict=False):
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
        """Compute keyword similarity scores using TF-IDF."""
        from app.rag.preprocessing.keyword import JiebaKeywordTableHandler

        keyword_table_handler = JiebaKeywordTableHandler()
        query_keywords = keyword_table_handler.extract_keywords(query, None)
        documents_keywords = []

        for document in documents:
            document_keywords = keyword_table_handler.extract_keywords(document.page_content, None)
            if document.metadata is not None:
                document.metadata["keywords"] = document_keywords
            documents_keywords.append(document_keywords)

        query_keyword_counts = Counter(query_keywords)
        total_documents = len(documents)
        keyword_idf = self._keyword_idf(documents_keywords, total_documents=total_documents)
        query_tfidf = self._tfidf_vector(query_keyword_counts, keyword_idf)
        documents_tfidf = [
            self._tfidf_vector(Counter(document_keywords), keyword_idf)
            for document_keywords in documents_keywords
        ]
        return [self._cosine_similarity(query_tfidf, document_tfidf) for document_tfidf in documents_tfidf]

    @staticmethod
    def _keyword_idf(documents_keywords: list[list[str]], *, total_documents: int) -> dict[str, float]:
        all_keywords: set[str] = set()
        for document_keywords in documents_keywords:
            all_keywords.update(document_keywords)

        keyword_idf: dict[str, float] = {}
        for keyword in all_keywords:
            doc_count_containing_keyword = sum(1 for doc_keywords in documents_keywords if keyword in doc_keywords)
            keyword_idf[keyword] = math.log((1 + total_documents) / (1 + doc_count_containing_keyword)) + 1
        return keyword_idf

    @staticmethod
    def _tfidf_vector(keyword_counts: Counter[str], keyword_idf: dict[str, float]) -> dict[str, float]:
        return {
            keyword: count * keyword_idf.get(keyword, 0)
            for keyword, count in keyword_counts.items()
        }

    @staticmethod
    def _cosine_similarity(vec1: dict[str, float], vec2: dict[str, float]) -> float:
        intersection = set(vec1.keys()) & set(vec2.keys())
        numerator = sum(vec1[key] * vec2[key] for key in intersection)
        denominator = math.sqrt(sum(value**2 for value in vec1.values())) * math.sqrt(
            sum(value**2 for value in vec2.values())
        )
        if not denominator:
            return 0.0
        return float(numerator) / denominator

    def _calculate_cosine(
        self, query: str, documents: list[Document], vector_setting: VectorSetting
    ) -> list[float]:
        """Compute cosine similarity scores using embeddings."""
        _ = vector_setting
        query_vector_scores = []

        # Get the query vector.
        if self.embedding_fn:
            query_vector = self.embedding_fn(query)
        else:
            # If no embedding function is provided, return existing scores.
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
