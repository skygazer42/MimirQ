"""
RAG Chunking module.

Provides document chunking functionality:
- factory: Chunker factory for different strategies
- hierarchical: Hierarchical markdown chunking
- splitters: Text splitters (recursive, semantic)
- legacy: Ragflow legacy chunkers (naive, book, laws, email)
"""

from app.rag.chunking.factory import chunker_factory

__all__ = ["chunker_factory"]
