"""
RAG Chunking module.

Provides document chunking functionality with multiple strategies:

Standard Chunkers (pure splitting, no parsing):
- chunker_factory: Factory for creating chunker instances
- strategies: LangChain-based and custom chunking algorithms

Integrated pipeline (integrated parsing + chunking):
- integrated: Full document processing pipeline (parse + chunk)

Utilities:
- hierarchical_chunk_markdown: Two-level paragraph/sentence chunking

Usage:
    # Standard chunking (for pre-parsed documents)
    from app.rag.chunking import chunker_factory
    chunker = chunker_factory.get_chunker("langchain_recursive", 1000, 200)
    chunks = chunker.split_documents(documents)

    # Integrated pipeline (for raw files; parse + chunk in one pass)
    from app.rag.chunking.integrated_pipeline import chunk_file
    chunks = chunk_file(path, strategy="integrated_naive")

    # Hierarchical markdown chunking
    from app.rag.chunking import hierarchical_chunk_markdown
    result = hierarchical_chunk_markdown(markdown_text)
"""
from app.rag.chunking.factory import chunker_factory
from app.rag.chunking.utils.hierarchical import hierarchical_chunk_markdown


def integrated_chunk_file(*args, **kwargs):
    """Backward compatible entrypoint for integrated parse+chunk (lazy import)."""
    from app.rag.chunking.integrated_pipeline.bridge import chunk_file

    return chunk_file(*args, **kwargs)

__all__ = [
    "chunker_factory",
    "hierarchical_chunk_markdown",
    "integrated_chunk_file",
]
