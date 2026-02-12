"""
Chunking utility functions and splitters.

Provides:
- hierarchical_chunk_markdown: Two-level paragraph/sentence chunking for Markdown
- splitters: Text splitters (RecursiveCharacterTextSplitter, etc.)
"""
from app.rag.chunking.utils.hierarchical import hierarchical_chunk_markdown
from app.rag.chunking.utils.splitters import (
    EnhanceRecursiveCharacterTextSplitter,
    FixedRecursiveCharacterTextSplitter,
    RecursiveCharacterTextSplitter,
    TextSplitter,
    Tokenizer,
    TokenTextSplitter,
    split_text_on_tokens,
)

__all__ = [
    "hierarchical_chunk_markdown",
    # Splitters
    "TextSplitter",
    "TokenTextSplitter",
    "RecursiveCharacterTextSplitter",
    "Tokenizer",
    "split_text_on_tokens",
    "EnhanceRecursiveCharacterTextSplitter",
    "FixedRecursiveCharacterTextSplitter",
]
