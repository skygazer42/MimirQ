from __future__ import annotations

import asyncio
from uuid import UUID

import pytest


@pytest.mark.asyncio
async def test_kg_recall_can_filter_skill_entities(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.kg.search.recall as recall_mod
    from app.rag.kg.search.config import SearchConfig
    from app.rag.kg.search.recall import RecallSearcher

    class _FakeSession:
        def close(self) -> None:
            return

    monkeypatch.setattr(recall_mod, "get_session", lambda: _FakeSession(), raising=True)

    async def _fake_generate_embedding(self, _text: str):  # noqa: ANN001
        await asyncio.sleep(0)  # Sonar S7503
        return [0.0]

    monkeypatch.setattr(recall_mod.DocumentProcessor, "generate_embedding", _fake_generate_embedding, raising=True)

    class _FakeEntityRepository:
        def __init__(self, _session):  # noqa: ANN001
            return

        def search_similar(self, *, query_vector, tenant_id, k, entity_type=None):  # noqa: ANN001
            assert query_vector
            assert tenant_id
            assert k
            return [
                {"entity_id": str(UUID(int=10)), "name": "S1", "type": "Skill", "similarity": 0.9},
                {"entity_id": str(UUID(int=11)), "name": "E1", "type": "Tool", "similarity": 0.8},
            ]

    class _FakeEventRepository:
        def __init__(self, _session):  # noqa: ANN001
            return

        def search_events_by_entities(self, *_a, **_k):  # noqa: ANN001
            return []

        def search_similar_by_content(self, *_a, **_k):  # noqa: ANN001
            return []

        def get_events_by_ids(self, *_a, **_k):  # noqa: ANN001
            return []

        def get_event_entities(self, *_a, **_k):  # noqa: ANN001
            return {}

    monkeypatch.setattr(recall_mod, "EntityRepository", _FakeEntityRepository, raising=True)
    monkeypatch.setattr(recall_mod, "EventRepository", _FakeEventRepository, raising=True)

    # Default: includes skills.
    cfg = SearchConfig(query="q", tenant_id=UUID(int=1), relation_expansion_enabled=False, include_skill_entities=True)
    res = await RecallSearcher().search(cfg)
    assert {str(e.get("type")) for e in (res.key_final or [])} == {"Skill", "Tool"}

    # Ablation: exclude skill-like entities.
    cfg2 = SearchConfig(query="q", tenant_id=UUID(int=1), relation_expansion_enabled=False, include_skill_entities=False)
    res2 = await RecallSearcher().search(cfg2)
    assert {str(e.get("type")) for e in (res2.key_final or [])} == {"Tool"}

