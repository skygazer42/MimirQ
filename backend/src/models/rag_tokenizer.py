"""
Minimal tokenizer helpers required by the DeepDoc parsers.

The original project ships a much richer tokenizer package.  To keep this
repository self-contained we provide a lightweight approximation backed by
jieba so that DeepDoc can run without additional private dependencies.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Iterable

import jieba
import jieba.posseg as pseg


def _normalize_text(text: str | None) -> str:
    return text or ""


def tokenize(text: str | None) -> str:
    """
    Tokenize text into a space separated string (compatible with upstream API).
    """
    normalized = _normalize_text(text)
    if not normalized:
        return ""
    tokens: Iterable[str] = jieba.cut(normalized, HMM=False)
    return " ".join(tokens)


@lru_cache(maxsize=2048)
def _tag_single(token: str) -> str:
    if not token:
        return ""
    result = next(pseg.cut(token, HMM=False), None)
    return result.flag if result else ""


def tag(token: str | None) -> str:
    """
    Return the coarse part-of-speech tag for the provided token.
    """
    normalized = _normalize_text(token)
    if not normalized:
        return ""
    return _tag_single(normalized)


def is_chinese(char: str | None) -> bool:
    """
    Detect whether the supplied character is a CJK ideograph.
    """
    if not char:
        return False
    code_point = ord(char)
    return 0x4E00 <= code_point <= 0x9FFF
