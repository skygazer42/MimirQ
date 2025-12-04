"""
Namespace for lightweight tokenizer helpers used by DeepDoc.
"""

from .rag_tokenizer import is_chinese, tag, tokenize

__all__ = ["is_chinese", "tag", "tokenize"]
