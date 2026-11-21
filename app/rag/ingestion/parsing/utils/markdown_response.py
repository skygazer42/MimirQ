# Fence normalization includes adaptations from InfiniFlow DeepDoc (Apache-2.0); see NOTICE.
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


def strip_markdown_code_fence(text: str) -> str:
    """Remove the outer fence from a model's Markdown response."""
    stripped = text.strip()
    lines = stripped.splitlines(keepends=True)
    if len(lines) >= 2 and lines[0].strip().lower() in {"```", "```markdown"} and lines[-1].strip() == "```":
        return "".join(lines[1:-1]).strip()
    return stripped


__all__ = ["extract_markdown_response_text", "strip_markdown_code_fence"]
