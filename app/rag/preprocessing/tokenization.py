"""
Shared tokenization helpers.

These are used across:
- BM25 retrieval
- Long-term memory retrieval (BM25 over chat history)
"""


from typing import List

import jieba

from app.rag.preprocessing.stopwords import STOPWORDS


def tokenize_for_bm25(text: str) -> List[str]:
    """
    Tokenize text for BM25.

    Notes:
    - Uses jieba search mode.
    - Applies conservative filters: stopwords, empty tokens, single-character tokens.
    """
    raw = (text or "").strip()
    if not raw:
        return []

    tokens: List[str] = []
    for token in jieba.cut_for_search(raw):
        tok = str(token).strip()
        if not tok:
            continue
        norm = tok.casefold() if tok.isascii() else tok
        if norm in STOPWORDS:
            continue
        # Skip single-character tokens (too noisy for BM25).
        if len(norm) < 2:
            continue
        tokens.append(norm)
    return tokens

