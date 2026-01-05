"""
Conversation helpers shared by different RAG pipelines.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def format_history_text(
    history: Optional[List[Dict[str, Any]]],
    *,
    window: int,
    empty_placeholder: str = "（无历史对话）",
    user_label: str = "用户",
    assistant_label: str = "助手",
) -> str:
    """
    Format chat history into a prompt-friendly text block.

    Supports a list of dict messages like: {"role": "user"|"assistant", "content": "..."}.
    """
    if not history:
        return empty_placeholder

    window = max(int(window or 0), 0)
    hist_slice = history[-window:] if window else []
    if not hist_slice:
        return empty_placeholder

    parts: list[str] = []
    for msg in hist_slice:
        if isinstance(msg, dict):
            role_value = msg.get("role")
            content_value = msg.get("content", "")
        else:
            role_value = getattr(msg, "role", None)
            content_value = getattr(msg, "content", "")

        role = user_label if role_value == "user" else assistant_label
        parts.append(f"{role}: {content_value}")

    text = "\n\n".join(parts).strip()
    return text or empty_placeholder

