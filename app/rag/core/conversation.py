"""
Conversation helpers shared by different RAG pipelines.
"""


from typing import Any, Dict, List, Optional


def format_history_text(
    history: Optional[List[Dict[str, Any]]],
    *,
    window: int,
    empty_placeholder: str = "(No conversation history)",
    user_label: str = "User",
    assistant_label: str = "Assistant",
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

    # Preserve the latest system message even when using a small rolling window.
    # This enables summary-memory injection without requiring a large CHAT_HISTORY_WINDOW.
    if window and history:
        last_system = None
        for msg in reversed(history):
            if isinstance(msg, dict):
                role_value = msg.get("role")
            else:
                role_value = getattr(msg, "role", None)
            if role_value == "system":
                last_system = msg
                break
        if last_system is not None and last_system not in hist_slice:
            hist_slice = [last_system] + list(hist_slice)

    parts: list[str] = []
    for msg in hist_slice:
        if isinstance(msg, dict):
            role_value = msg.get("role")
            content_value = msg.get("content", "")
        else:
            role_value = getattr(msg, "role", None)
            content_value = getattr(msg, "content", "")

        if role_value == "system":
            role = "System"
        else:
            role = user_label if role_value == "user" else assistant_label
        parts.append(f"{role}: {content_value}")

    text = "\n\n".join(parts).strip()
    return text or empty_placeholder
