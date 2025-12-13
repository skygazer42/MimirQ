"""
Compatibility layer exposing the DeepDoc tokenizer under the legacy
`infinity.rag_tokenizer` module path so ragflow utilities keep working.
"""

from deepdoc.src.model.rag_tokenizer import (  # noqa: F401
    RagTokenizer,
    addUserDict,
    fine_grained_tokenize,
    freq,
    loadUserDict,
    rag_tokenizer as tokenizer,
    strQ2B,
    tag,
    tokenize,
    tradi2simp,
)

__all__ = [
    "RagTokenizer",
    "tokenizer",
    "tokenize",
    "fine_grained_tokenize",
    "tag",
    "freq",
    "loadUserDict",
    "addUserDict",
    "tradi2simp",
    "strQ2B",
]
