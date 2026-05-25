from __future__ import annotations

from uuid import UUID

import pytest


def test_local_factoid_skips_expand_for_precision() -> None:
    from app.rag.kg.search.config import SearchConfig
    from app.rag.kg.search.searcher import KGSearcher

    cfg = SearchConfig(
        query="Which paper proposed layer normalization?",
        tenant_id=UUID(int=1),
        dataset_id=UUID(int=2),
        account_id="acct",
        query_mode="local",
        query_mode_reason_codes=["dataset_factoid_scope"],
        query_mode_confidence="medium",
    )

    skip, reason = KGSearcher()._should_skip_expand_for_latency(
        config=cfg,
        query_mode="local",
        recalled_event_count=40,
    )

    assert skip is True
    assert reason == "local_factoid_precision"


@pytest.mark.asyncio
async def test_local_factoid_uses_rrf_without_expand(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.kg.search.searcher as searcher_mod
    from app.rag.kg.search.config import RerankStrategy, SearchConfig
    from app.rag.kg.search.recall import RecallResult
    from app.rag.kg.search.searcher import KGSearcher
    from app.rag.reranker.types import RerankResult

    captured: dict[str, object] = {}

    class _FakeRecall:
        async def search(self, _config):  # noqa: ANN001
            return RecallResult(
                query_vector=[],
                key_final=[],
                event_ids=["event-1"],
                clues=[],
                key_weights={},
                event_scores={"event-1": 1.0},
                event_hops={},
            )

    class _FailingExpand:
        async def expand(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
            raise AssertionError("local factoid search should not expand")

    class _FakeReranker:
        async def arerank_kg(self, **_kwargs):  # noqa: ANN003
            return RerankResult(
                ordered_ids=["event-1"],
                score_map={"event-1": 1.0},
                items=[{"id": "event-1", "score": 1.0}],
                stats={},
            )

    def _fake_get_kg_reranker(strategy):  # noqa: ANN001
        captured["strategy"] = strategy
        return _FakeReranker()

    monkeypatch.setattr(searcher_mod, "get_kg_reranker", _fake_get_kg_reranker, raising=True)

    searcher = KGSearcher()
    searcher.recall_searcher = _FakeRecall()
    searcher.expand_searcher = _FailingExpand()

    cfg = SearchConfig(
        query="Which paper proposed layer normalization?",
        tenant_id=UUID(int=1),
        dataset_id=UUID(int=2),
        account_id="acct",
        query_mode="local",
        query_mode_reason_codes=["dataset_factoid_scope"],
        query_mode_confidence="medium",
    )

    out = await searcher.search(cfg)

    assert out["events"] == [{"id": "event-1", "score": 1.0}]
    assert captured["strategy"] == RerankStrategy.RRF
    assert out["stats"]["expand_skipped"] is True
    assert out["stats"]["expand_skipped_reason"] == "local_factoid_precision"
