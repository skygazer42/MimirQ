"""Shared chunking hierarchy and format detection utilities."""

import json
import re

from app.rag.chunking.utils.hierarchical import hierarchical_chunk_markdown

_MD_HINT_RES = (
    re.compile(r"(?m)^\s*#{1,6}\s+"),
    re.compile(r"\[[^\]]+\]\([^)]+\)"),
    re.compile(r"(?m)^\s*```"),
    re.compile(r"(?m)^\s*[-*+]\s+"),
)


def looks_like_markdown(text: str) -> bool:
    if not text or len(text) < 20:
        return False
    return any(p.search(text) for p in _MD_HINT_RES)


def looks_like_json(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False
    if stripped[0] not in "{[":
        return False
    try:
        json.loads(stripped)
        return True
    except Exception:
        return False


__all__ = [
    "hierarchical_chunk_markdown",
    "looks_like_json",
    "looks_like_markdown",
]
