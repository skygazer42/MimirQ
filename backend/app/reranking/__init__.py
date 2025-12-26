"""
Compatibility shim.

Prefer importing from `app.rag.reranking`.
"""

from app.rag.reranking.kg import KgReranker, get_kg_reranker
from app.rag.reranking.rag import RagLlmReranker, RagParentChildReranker, get_rag_reranker
from app.rag.reranking.types import AsyncReranker, RerankCandidate, RerankResult, SyncReranker

__all__ = [
    "AsyncReranker",
    "RerankCandidate",
    "RerankResult",
    "SyncReranker",
    "KgReranker",
    "RagLlmReranker",
    "RagParentChildReranker",
    "get_kg_reranker",
    "get_rag_reranker",
]
