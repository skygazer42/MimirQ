from __future__ import annotations

from types import SimpleNamespace

from app.rag.core.conversation import format_history_text


def test_format_history_text_preserves_latest_system_message_outside_window() -> None:
    history = [
        {"role": "system", "content": "old system"},
        SimpleNamespace(role="system", content="latest system"),
        {"role": "user", "content": "first"},
        SimpleNamespace(role="assistant", content="second"),
    ]

    assert format_history_text(history, window=2, user_label="Human", assistant_label="Bot") == (
        "System: latest system\n\nHuman: first\n\nBot: second"
    )


def test_format_history_text_uses_placeholder_for_zero_window() -> None:
    assert format_history_text([{"role": "user", "content": "ignored"}], window=0, empty_placeholder="empty") == (
        "empty"
    )
