"""
Code-fence extraction helpers.

We intentionally avoid regex for code-fence parsing to keep runtime linear-time and
to avoid catastrophic-backtracking hotspots.
"""

from __future__ import annotations

from collections.abc import Iterable


def extract_first_code_fence(text: str, *, allowed_info_strings: Iterable[str] | None = None) -> str | None:
    """
    Extract the first triple-backtick code fence content.

    Args:
        text: Input text, potentially containing fenced blocks.
        allowed_info_strings: Optional allowlist of info strings (language tags)
          to accept. Examples: {"", "json"}, {"", "sql"}.

    Returns:
        The inner fenced content (trimmed), or None if no allowed fence is found.
    """
    raw = text or ""
    if not raw:
        return None

    allowed: set[str] | None = None
    if allowed_info_strings is not None:
        allowed = {(s or "").strip().lower() for s in allowed_info_strings}

    lower = raw.lower()
    start = lower.find("```")
    while start != -1:
        # Determine the opening fence's info string (until newline/end).
        line_end = raw.find("\n", start + 3)
        if line_end == -1:
            line_end = len(raw)
        info = raw[start + 3 : line_end].strip().lower()
        if allowed is not None and info not in allowed:
            start = lower.find("```", start + 3)
            continue

        content_start = line_end + 1 if line_end < len(raw) else line_end
        end = lower.find("```", content_start)
        if end == -1:
            return None
        inner = raw[content_start:end].strip()
        return inner or None

    return None


__all__ = ["extract_first_code_fence"]
