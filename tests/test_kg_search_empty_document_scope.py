from __future__ import annotations

from uuid import UUID

import pytest

from tests.helpers.async_utils import yield_control


@pytest.mark.asyncio
async def test_recall_searcher_empty_document_ids_short_circuits(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.kg.search.recall as recall_mod
    from app.rag.kg.search.config import SearchConfig
    from app.rag.kg.search.recall import RecallSearcher

    async def _should_not_be_called(self, *_a, **_k):  # noqa: ANN001
        await yield_control()
        raise AssertionError("generate_embedding should not run for empty document scope")

    monkeypatch.setattr(recall_mod.DocumentProcessor, "generate_embedding", _should_not_be_called, raising=True)

    cfg = SearchConfig(query="q", tenant_id=UUID(int=1), document_ids=[])
    out = await RecallSearcher().search(cfg)

    assert out.event_ids == []
    assert out.key_final == []
    assert out.query_vector == []
    assert out.relation_debug.get("reason") == "empty_document_scope"


@pytest.mark.asyncio
async def test_expand_searcher_empty_document_ids_returns_empty() -> None:
    from app.rag.kg.search.config import SearchConfig
    from app.rag.kg.search.expand import ExpandSearcher
    from app.rag.kg.search.recall import RecallResult

    cfg = SearchConfig(query="q", tenant_id=UUID(int=1), document_ids=[])
    recall_result = RecallResult(
        query_vector=[1.0],
        key_final=[{"entity_id": str(UUID(int=2)), "name": "Alice", "type": "Person", "weight": 1.0}],
        event_ids=[str(UUID(int=3))],
        clues=[{"id": "c"}],
        key_weights={},
        event_scores={},
    )

    out = await ExpandSearcher().expand(cfg, recall_result)
    assert out.event_ids == []
    assert out.key_final == []

