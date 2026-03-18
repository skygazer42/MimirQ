from __future__ import annotations

import json

import httpx
import pytest


@pytest.mark.asyncio
async def test_stream_vision_chat_completions_tokens_parses_sse(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings
    from app.rag.core.vision_reader import stream_vision_chat_completions_tokens

    monkeypatch.setattr(settings, "VISION_LLM_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "VISION_LLM_API_KEY", "test-key", raising=False)
    monkeypatch.setattr(settings, "VISION_LLM_API_BASE", "http://test/v1", raising=False)
    monkeypatch.setattr(settings, "VISION_LLM_MODEL", "gpt-4o-mini", raising=False)
    monkeypatch.setattr(settings, "VISION_LLM_TIMEOUT_SEC", 10, raising=False)
    monkeypatch.setattr(settings, "VISION_LLM_MAX_TOKENS", 64, raising=False)
    monkeypatch.setattr(settings, "VISION_LLM_TEMPERATURE", 0.0, raising=False)

    def _handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        body = json.loads((request.content or b"{}").decode("utf-8", "ignore") or "{}")
        assert body["model"] == "gpt-4o-mini"
        assert body["stream"] is True
        assert isinstance(body["messages"], list)

        sse = "\n".join(
            [
                'data: {"choices":[{"delta":{"content":"Hello"}}]}',
                "",
                'data: {"choices":[{"delta":{"content":" world"}}]}',
                "",
                "data: [DONE]",
                "",
            ]
        ).encode("utf-8")
        return httpx.Response(200, content=sse)

    transport = httpx.MockTransport(_handler)
    async with httpx.AsyncClient(transport=transport) as client:
        tokens: list[str] = []
        async for t in stream_vision_chat_completions_tokens(
            http_client=client,
            messages=[{"role": "user", "content": [{"type": "text", "text": "hi"}]}],
        ):
            tokens.append(t)

    assert "".join(tokens) == "Hello world"

