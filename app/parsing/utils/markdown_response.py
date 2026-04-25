from __future__ import annotations

from typing import Any

_MARKDOWN_CANDIDATE_KEYS = ("markdown", "md", "content", "text", "output")
_MARKDOWN_NESTED_KEYS = ("data", "result")


def extract_markdown_response_text(payload: Any, *, max_depth: int = 3) -> str:
    """
    Best-effort extract markdown/text content from parser JSON payloads.

    Supports:
    - top-level keys: markdown/md/content/text/output
    - nested wrappers like {"data": {...}} / {"result": {...}}
    """
    if max_depth < 0:
        return ""
    if isinstance(payload, str):
        return payload if payload.strip() else ""
    if not isinstance(payload, dict):
        return ""

    for key in _MARKDOWN_CANDIDATE_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value

    for key in _MARKDOWN_NESTED_KEYS:
        value = payload.get(key)
        text = extract_markdown_response_text(value, max_depth=max_depth - 1)
        if text:
            return text

    return ""


__all__ = ["extract_markdown_response_text"]
