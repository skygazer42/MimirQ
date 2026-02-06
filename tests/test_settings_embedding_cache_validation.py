from __future__ import annotations

import pytest


def test_settings_rejects_negative_embedding_cache_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("EMBEDDING_CACHE_TTL_SEC", "-1")
    with pytest.raises(ValueError):
        Settings()


def test_settings_rejects_empty_embedding_cache_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("EMBEDDING_CACHE_PREFIX", "   ")
    with pytest.raises(ValueError):
        Settings()


def test_settings_strips_embedding_cache_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("EMBEDDING_CACHE_PREFIX", "  emb  ")
    s = Settings()
    assert s.EMBEDDING_CACHE_PREFIX == "emb"
