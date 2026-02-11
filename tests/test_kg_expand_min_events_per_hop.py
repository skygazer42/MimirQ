from __future__ import annotations

from uuid import UUID

import pytest


@pytest.mark.asyncio
async def test_expand_stops_when_new_events_below_min_events_per_hop(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.kg.search.expand as expand_mod
    from app.rag.kg.search.config import ExpandConfig, RecallConfig, RerankConfig, SearchConfig
    from app.rag.kg.search.expand import ExpandSearcher
    from app.rag.kg.search.recall import RecallResult

    class _FakeSession:
        def close(self) -> None:
            return

    monkeypatch.setattr(expand_mod, "get_session", lambda: _FakeSession(), raising=True)

    calls = {"find": 0}

    class _Ev:
        def __init__(self, ev_id: UUID):  # noqa: D401
            self.id = ev_id
            self.title = "t"
            self.summary = ""
            self.content = ""

    class _Ent:
        def __init__(self, ent_id: UUID, name: str, type_: str):  # noqa: D401
            self.id = ent_id
            self.name = name
            self.type = type_

    class _FakeEntityRepository:
        def __init__(self, _session):  # noqa: ANN001
            return

        def get_entities_by_ids(self, _ids, *, tenant_id=None):  # noqa: ANN001
            return [
                _Ent(UUID(int=10), "A", "t"),
                _Ent(UUID(int=11), "B", "t"),
                _Ent(UUID(int=12), "C", "t"),
            ]

    class _FakeEventRepository:
        def __init__(self, _session):  # noqa: ANN001
            return

        def find_events_by_entities(self, _entity_ids, tenant_id, limit=50, document_ids=None, **_k):  # noqa: ANN001
            calls["find"] += 1
            assert tenant_id
            assert limit > 0
            return [_Ev(UUID(int=101)), _Ev(UUID(int=102))]

        def get_entities_for_events(self, event_ids, tenant_id):  # noqa: ANN001
            assert tenant_id
            return {
                str(UUID(int=101)): [_Ent(UUID(int=11), "B", "t")],
                str(UUID(int=102)): [_Ent(UUID(int=12), "C", "t")],
            }

    monkeypatch.setattr(expand_mod, "EntityRepository", _FakeEntityRepository, raising=True)
    monkeypatch.setattr(expand_mod, "EventRepository", _FakeEventRepository, raising=True)

    config = SearchConfig(
        query="q",
        tenant_id=UUID(int=1),
        document_ids=[UUID(int=2)],
        recall=RecallConfig(),
        expand=ExpandConfig(enabled=True, max_hops=3, entities_per_hop=10, min_events_per_hop=3, max_events_per_hop=60),
        rerank=RerankConfig(),
    )
    recall_result = RecallResult(
        query_vector=[0.0],
        key_final=[{"entity_id": str(UUID(int=10)), "name": "A", "type": "t", "weight": 1.0}],
        event_ids=[str(UUID(int=100))],
        clues=[],
        key_weights={str(UUID(int=10)): 1.0},
        event_scores={str(UUID(int=100)): 0.5},
    )

    result = await ExpandSearcher().expand(config, recall_result)

    assert calls["find"] == 1
    assert set(result.event_ids) == {str(UUID(int=100)), str(UUID(int=101)), str(UUID(int=102))}
