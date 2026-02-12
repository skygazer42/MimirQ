"""
Integrated pipeline chunking pipeline.

Integrated parsing + chunking strategies from Integrated pipeline project.
Specialized for different document types.

Available chunkers:
- naive_chunk: General-purpose chunking (PDF, DOCX, Markdown, etc.)
- book_chunk: Book format (chapter/section structure)
- laws_chunk: Legal documents
- email_chunk: Email format

Usage:
    # High-level API
    from app.third_party.integrated_pipeline.bridge import chunk_file
    chunks = chunk_file(path, strategy="integrated_naive")

    # Low-level API
    from app.third_party.integrated_pipeline.chunkers import naive_chunk, book_chunk
    from app.third_party.integrated_pipeline.nlp import rag_tokenizer, find_codec
    from app.third_party.integrated_pipeline.common import num_tokens_from_string
"""
from app.third_party.integrated_pipeline.bridge import ChunkStrategy, chunk_file

__all__ = [
    "chunk_file",
    "ChunkStrategy",
    "chunkers",
    "nlp",
    "common",
]
