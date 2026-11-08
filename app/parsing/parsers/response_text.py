"""Shared text extraction from parser service JSON responses."""

from typing import Any


def extract_markdown_from_json(data: Any) -> str:
    if isinstance(data, dict):
        for key in ("markdown", "md", "content", "text", "result"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value
    return ""


__all__ = ["extract_markdown_from_json"]
