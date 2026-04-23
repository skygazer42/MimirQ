from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

import pytest


@pytest.mark.asyncio
async def test_kg_search_attaches_path_renderings_to_event_results(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.kg.search.searcher as searcher_mod
    from app.core.config import settings
    from app.rag.kg.search.config import SearchConfig

    monkeypatch.setattr(settings, "KG_COMMUNITY_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "KG_SEARCH_METRICS_ENABLED", False, raising=False)

    searcher = searcher_mod.KGSearcher()

    async def _fake_recall(_config):  # noqa: ANN001
        return SimpleNamespace(
            key_final=[
                {"entity_id": "e-plc", "name": "PLC-7", "type": "Device", "weight": 0.9},
                {"entity_id": "e-coolant", "name": "Cooling Loop", "type": "Subsystem", "weight": 0.8},
            ],
            event_ids=["ev-1"],
            clues=[],
            event_scores={"ev-1": 0.8},
            query_vector=[0.1],
            relation_debug={},
        )

    async def _fake_expand(_config, recall_result):  # noqa: ANN001
        return SimpleNamespace(
            key_final=list(recall_result.key_final),
            event_ids=["ev-1"],
            clues=[],
            event_scores={"ev-1": 0.8},
            event_hops={"ev-1": 2},
        )

    class _FakeReranker:
        async def arerank_kg(self, **_kwargs):  # noqa: ANN003
            return SimpleNamespace(
                items=[
                    {
                        "id": "ev-1",
                        "title": "PLC Temperature Alarm",
                        "summary": "Alarm triggered after coolant failure.",
                        "score": 0.91,
                        "kg_path": [
                            {"entity_id": "e-plc", "type": "Device"},
                            {"entity_id": "e-coolant", "type": "Subsystem"},
                        ],
                    }
                ],
                clues=[],
                stats={},
            )

    monkeypatch.setattr(searcher.recall_searcher, "search", _fake_recall, raising=True)
    monkeypatch.setattr(searcher.expand_searcher, "expand", _fake_expand, raising=True)
    monkeypatch.setattr(searcher_mod, "get_kg_reranker", lambda _strategy: _FakeReranker(), raising=True)

    out = await searcher._search_impl(
        SearchConfig(
            query="Why did the PLC overheat?",
            tenant_id=UUID(int=1),
            dataset_id=UUID(int=2),
            account_id="u",
            query_mode="local",
        )
    )

    events = out.get("events") or []
    assert len(events) == 1
    renderings = events[0].get("kg_path_renderings")
    assert isinstance(renderings, dict)
    assert renderings.get("schema") == "mimirq.kg_path_renderings.v1"
    assert "PLC-7 [Device]" in str(renderings.get("path_string") or "")
    assert "PLC Temperature Alarm" in str(renderings.get("reasoning_chain") or "")

