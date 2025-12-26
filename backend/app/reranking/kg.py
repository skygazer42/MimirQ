"""
Compatibility shim.

Prefer importing from `app.rag.reranking.kg`.
"""

from app.rag.reranking.kg import KgReranker, get_kg_reranker

__all__ = ["KgReranker", "get_kg_reranker"]
