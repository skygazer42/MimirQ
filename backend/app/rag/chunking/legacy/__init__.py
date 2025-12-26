"""
Legacy chunking strategies (naive, book, laws, email).
These were integrated from ragflow and provide specialized document chunking.

Usage:
    from app.rag.chunking.legacy.chunkers import naive_chunk, book_chunk
    from app.rag.chunking.legacy.nlp import rag_tokenizer, find_codec
    from app.rag.chunking.legacy.common import num_tokens_from_string
"""

__all__ = ['chunkers', 'nlp', 'common']
