from __future__ import annotations

import asyncio

import pytest


@pytest.mark.asyncio
async def test_kg_searcher_respects_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import config as config_mod

    monkeypatch.setattr(config_mod.settings, "KG_SEARCH_TIMEOUT_SEC", 0.01, raising=False)

    from app.rag.kg.search.config import SearchConfig
    from app.rag.kg.search.searcher import KGSearcher

    searcher = KGSearcher()

    async def _slow(_config):  # noqa: ANN001
        await asyncio.sleep(0.05)
        return {}

    monkeypatch.setattr(searcher, "_search_impl", _slow, raising=True)

    with pytest.raises(asyncio.TimeoutError):
        await searcher.search(SearchConfig(query="q"))
