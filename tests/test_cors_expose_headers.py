from __future__ import annotations

from app.core.config import Settings
from app.core.utils import parse_csv
from app.main import _build_cors_expose_headers


def test_cors_exposes_stream_chat_conversation_headers_by_default() -> None:
    default_headers = str(Settings.model_fields["CORS_EXPOSE_HEADERS"].default)
    headers = set(parse_csv(default_headers))

    assert "X-Request-ID" in headers
    assert "X-Conversation-ID" in headers
    assert "X-Assistant-Message-ID" in headers


def test_cors_expose_builder_keeps_stream_chat_headers_with_env_override() -> None:
    headers = _build_cors_expose_headers("X-Request-ID,X-Process-Time-Ms,Retry-After")

    assert headers == [
        "X-Request-ID",
        "X-Process-Time-Ms",
        "Retry-After",
        "X-Conversation-ID",
        "X-Assistant-Message-ID",
    ]
