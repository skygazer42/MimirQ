"""
RAG Chunking module.

Provides document chunking functionality with multiple strategies:

Standard Chunkers (pure splitting, no parsing):
- chunker_factory: Factory for creating chunker instances
- strategies: LangChain-based and custom chunking algorithms

RAGFlow Pipeline (integrated parsing + chunking):
- ragflow: Full document processing pipeline from RAGFlow

Utilities:
- hierarchical_chunk_markdown: Two-level paragraph/sentence chunking

Usage:
    # Standard chunking (for pre-parsed documents)
    from app.rag.chunking import chunker_factory
    chunker = chunker_factory.get_chunker("langchain_recursive", 1000, 200)
    chunks = chunker.split_documents(documents)

    # RAGFlow pipeline (for raw files)
    from app.rag.chunking.ragflow import chunk_file
    chunks = chunk_file(path, strategy="ragflow_naive")

    # Hierarchical markdown chunking
    from app.rag.chunking import hierarchical_chunk_markdown
    result = hierarchical_chunk_markdown(markdown_text)
"""
from app.rag.chunking.factory import chunker_factory
from app.rag.chunking.utils.hierarchical import hierarchical_chunk_markdown


def ragflow_chunk_file(*args, **kwargs):
    """Backward compatible entrypoint for RAGFlow pipeline (lazy import)."""
    from app.rag.chunking.ragflow.bridge import chunk_file

    return chunk_file(*args, **kwargs)

__all__ = [
    "chunker_factory",
    "hierarchical_chunk_markdown",
    "ragflow_chunk_file",
]
