"""
RAG Retrieval module.

Provides hybrid retrieval (vector + BM25) functionality.
"""

from app.rag.retrieval.hybrid_retriever import HybridRetriever, hybrid_retriever

__all__ = ["HybridRetriever", "hybrid_retriever"]
