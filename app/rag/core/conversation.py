"""
Conversation helpers shared by different RAG pipelines.
"""

from typing import Any


def format_history_text(
    history: list[dict[str, Any]] | None,
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

    hist_slice = _with_latest_system_message(history, hist_slice)
    parts = [
        _format_history_message(message, user_label=user_label, assistant_label=assistant_label)
        for message in hist_slice
    ]

    text = "\n\n".join(parts).strip()
    return text or empty_placeholder


def _message_value(message: Any, field_name: str, default: Any = None) -> Any:
    if isinstance(message, dict):
        return message.get(field_name, default)
    return getattr(message, field_name, default)


def _with_latest_system_message(history: list[Any], window_messages: list[Any]) -> list[Any]:
    """Keep summary memory available even when it falls outside the rolling window."""
    latest_system = next(
        (message for message in reversed(history) if _message_value(message, "role") == "system"),
        None,
    )
    if latest_system is None or latest_system in window_messages:
        return window_messages
    return [latest_system, *window_messages]


def _format_history_message(message: Any, *, user_label: str, assistant_label: str) -> str:
    role_value = _message_value(message, "role")
    content = _message_value(message, "content", "")
    if role_value == "system":
        role = "System"
    else:
        role = user_label if role_value == "user" else assistant_label
    return f"{role}: {content}"
