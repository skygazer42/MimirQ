"""
RAGFlow chunking pipeline.

Integrated parsing + chunking strategies from RAGFlow project.
Specialized for different document types.

Available chunkers:
- naive_chunk: General-purpose chunking (PDF, DOCX, Markdown, etc.)
- book_chunk: Book format (chapter/section structure)
- laws_chunk: Legal documents
- email_chunk: Email format

Usage:
    # High-level API
    from app.third_party.ragflow.bridge import chunk_file
    chunks = chunk_file(path, strategy="ragflow_naive")

    # Low-level API
    from app.third_party.ragflow.chunkers import naive_chunk, book_chunk
    from app.third_party.ragflow.nlp import rag_tokenizer, find_codec
    from app.third_party.ragflow.common import num_tokens_from_string
"""
from app.third_party.ragflow.bridge import ChunkStrategy, chunk_file

__all__ = [
    "chunk_file",
    "ChunkStrategy",
    "chunkers",
    "nlp",
    "common",
]
