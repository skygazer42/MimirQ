from __future__ import annotations

import pytest


def test_dashscope_encode_delegates_to_async_encoder(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.rag.embedding.providers.dashscope import DashScopeEmbedding

    model = DashScopeEmbedding(
        model="text-embedding-v4",
        dimension=1024,
        base_url="https://dashscope.example.test/embeddings",
        api_key="token",
    )

    async def _fake_aencode(message: str | list[str]) -> list[list[float]]:
        assert message == "hello"
        return [[0.25, 0.75]]

    monkeypatch.setattr(model, "aencode", _fake_aencode, raising=True)

    assert model.encode("hello") == [[0.25, 0.75]]
