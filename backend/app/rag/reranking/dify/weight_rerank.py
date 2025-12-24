"""
Weight-based reranking implementation.
Integrated from third_party/dify/rerank/weight_rerank.py
"""
import math
from collections import Counter
from typing import Callable

import numpy as np

from app.models.dify import Document
from app.parsing.keyword.jieba import JiebaKeywordTableHandler
from app.rag.reranking.dify.rerank_base import BaseRerankRunner
from app.rag.reranking.dify.entity import VectorSetting, Weights


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
        """Run weighted reranking.

        Args:
            query: Search query
            documents: Documents for reranking
            score_threshold: Minimum score threshold
            top_n: Maximum number of results
            user: User identifier (unused)

        Returns:
            Reranked documents
        """
        # Deduplicate documents
        unique_documents = []
        doc_ids = set()
        for document in documents:
            if (
                document.provider == "dify"
                and document.metadata is not None
                and document.metadata.get("doc_id") not in doc_ids
            ):
                doc_ids.add(document.metadata["doc_id"])
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
        """Calculate TF-IDF based keyword similarity scores.

        Args:
            query: Search query
            documents: Documents to score

        Returns:
            List of similarity scores
        """
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
        """Calculate cosine similarity scores using embeddings.

        Args:
            query: Search query
            documents: Documents to score
            vector_setting: Vector weight settings

        Returns:
            List of cosine similarity scores
        """
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
                # Calculate cosine similarity
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
