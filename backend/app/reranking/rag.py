"""
Compatibility shim.

Prefer importing from `app.rag.reranking.rag`.
"""

from app.rag.reranking.rag import RagLlmReranker, RagParentChildReranker, get_rag_reranker

__all__ = ["RagLlmReranker", "RagParentChildReranker", "get_rag_reranker"]
