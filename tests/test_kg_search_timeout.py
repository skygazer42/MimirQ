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


@pytest.mark.asyncio
async def test_kg_searcher_skips_expand_when_recall_consumes_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.kg.search.searcher as searcher_mod
    from app.core import config as config_mod
    from app.rag.kg.search.config import SearchConfig
    from app.rag.kg.search.recall import RecallResult
    from app.rag.kg.search.searcher import KGSearcher
    from app.rag.reranker.types import RerankResult

    monkeypatch.setattr(config_mod.settings, "KG_SEARCH_TIMEOUT_SEC", 0.0, raising=False)
    monkeypatch.setattr(config_mod.settings, "KG_SEARCH_EXPAND_BUDGET_SEC", 0.001, raising=False)
    monkeypatch.setattr(config_mod.settings, "KG_SEARCH_LATENCY_SLO_MS", 1, raising=False)

    class _SlowRecall:
        async def search(self, _config):  # noqa: ANN001
            await asyncio.sleep(0.01)
            return RecallResult(
                query_vector=[],
                key_final=["entity-1"],
                event_ids=["event-1"],
                clues=[],
                key_weights={},
                event_scores={"event-1": 1.0},
                event_hops={},
            )

    class _FailingExpand:
        async def expand(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
            raise AssertionError("expand should be skipped after recall budget is consumed")

    class _FakeReranker:
        async def arerank_kg(self, **_kwargs):  # noqa: ANN003
            return RerankResult(
                ordered_ids=["event-1"],
                score_map={"event-1": 1.0},
                items=[{"id": "event-1", "score": 1.0}],
                stats={},
            )

    monkeypatch.setattr(searcher_mod, "get_kg_reranker", lambda _strategy: _FakeReranker(), raising=True)

    searcher = KGSearcher()
    searcher.recall_searcher = _SlowRecall()
    searcher.expand_searcher = _FailingExpand()

    out = await searcher.search(SearchConfig(query="q", query_mode="global", query_mode_confidence="high"))

    assert out["stats"]["expand_skipped"] is True
    assert out["stats"]["expand_skipped_reason"] == "recall_budget_exhausted"
    assert out["stats"]["budget"]["expand_budget_exhausted"] is True
    assert out["stats"]["slo"]["exceeded"] is True
