from __future__ import annotations

import pytest


def test_settings_rejects_non_positive_retrieval_top_k(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("RETRIEVAL_TOP_K", "0")
    with pytest.raises(ValueError):
        Settings()


def test_settings_rejects_non_positive_rrf_k(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("RETRIEVAL_RRF_K", "0")
    with pytest.raises(ValueError):
        Settings()


def test_settings_rejects_invalid_dedup_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("RETRIEVAL_DEDUP_JACCARD_THRESHOLD", "1.5")
    with pytest.raises(ValueError):
        Settings()


def test_settings_rejects_negative_diversity_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("RETRIEVAL_MAX_CHUNKS_PER_DOC", "-1")
    with pytest.raises(ValueError):
        Settings()


def test_settings_rejects_negative_page_diversity_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import Settings

    monkeypatch.setenv("RETRIEVAL_MAX_CHUNKS_PER_PAGE", "-1")
    with pytest.raises(ValueError):
        Settings()
