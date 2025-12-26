"""
Unified document reranking runners (migrated from third_party/dify).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections import Counter
try:
    from enum import StrEnum
except ImportError:  # pragma: no cover
    from enum import Enum

    class StrEnum(str, Enum):
        pass
import math
from typing import Callable

from pydantic import BaseModel

from app.models.dify import Document


class BaseRerankRunner(ABC):
    """Base class for reranking runners operating on document lists."""

    @abstractmethod
    def run(
        self,
        query: str,
        documents: list[Document],
        score_threshold: float | None = None,
        top_n: int | None = None,
        user: str | None = None,
    ) -> list[Document]:
        """Run rerank model and return documents sorted by relevance."""
        raise NotImplementedError


class RerankMode(StrEnum):
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


class ParentChildRerankRunner(BaseRerankRunner):
    """Reranker that groups by parent_id and keeps the strongest child per parent."""

    def run(
        self,
        query: str,
        documents: list[Document],
        score_threshold: float | None = None,
        top_n: int | None = None,
        user: str | None = None,
    ) -> list[Document]:
        if not documents:
            return []

        groups: dict[str, list[Document]] = {}
        scores: dict[int, float] = {}
        for doc in documents:
            meta = doc.metadata or {}
            score = float(meta.get("score", 0.0) or 0.0)
            scores[id(doc)] = score
            group_id = meta.get("parent_id") or meta.get("parent_node_id")
            if not group_id:
                doc_id = meta.get("document_id")
                chunk_index = meta.get("chunk_index")
                if doc_id is not None and chunk_index is not None:
                    group_id = f"{doc_id}:{chunk_index}"
                else:
                    group_id = f"self:{id(doc)}"
            groups.setdefault(str(group_id), []).append(doc)

        ranked: list[tuple[Document, float]] = []
        for _, items in groups.items():
            children = [d for d in items if (d.metadata or {}).get("chunk_role") == "child"]
            if children:
                rep = max(children, key=lambda d: scores.get(id(d), 0.0))
            else:
                rep = max(items, key=lambda d: scores.get(id(d), 0.0))
            ranked.append((rep, scores.get(id(rep), 0.0)))

        ranked.sort(key=lambda x: x[1], reverse=True)

        output: list[Document] = []
        for doc, score in ranked:
            if score_threshold is not None and score < score_threshold:
                continue
            output.append(doc)
            if top_n and len(output) >= top_n:
                break

        return output


class WeightRerankRunner(BaseRerankRunner):
    """Reranker that combines vector similarity and keyword matching with configurable weights."""

    def __init__(
        self,
        tenant_id: str,
        weights: Weights,
        embedding_fn: Callable[[str], list[float]] | None = None,
    ):
        """Initialize the weight reranker.

        Args:
            tenant_id: Tenant identifier
            weights: Weight configuration for vector and keyword scores
            embedding_fn: Optional function to generate embeddings for query
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
        # Deduplicate documents by doc_id/document_id when available.
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

        # Calculate scores
        query_scores = self._calculate_keyword_score(query, documents)
        query_vector_scores = self._calculate_cosine(query, documents, self.weights.vector_setting)

        # Combine scores
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
        """Calculate TF-IDF based keyword similarity scores."""
        from app.governance.keyword import JiebaKeywordTableHandler

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
        """Calculate cosine similarity scores using embeddings."""
        query_vector_scores = []

        # Get query vector
        if self.embedding_fn:
            query_vector = self.embedding_fn(query)
        else:
            # Return existing scores if no embedding function
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
