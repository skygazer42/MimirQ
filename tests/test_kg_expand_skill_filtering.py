from __future__ import annotations

from uuid import UUID

import pytest


@pytest.mark.asyncio
async def test_kg_expand_can_filter_skill_entities(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.kg.search.expand as expand_mod
    from app.rag.kg.search.config import SearchConfig
    from app.rag.kg.search.expand import ExpandSearcher
    from app.rag.kg.search.recall import RecallResult

    class _FakeSession:
        def close(self) -> None:
            return

    monkeypatch.setattr(expand_mod, "get_session", lambda: _FakeSession(), raising=True)

    class _Ent:
        def __init__(self, ent_id: UUID, name: str, type_: str):
            self.id = ent_id
            self.name = name
            self.type = type_

    class _Ev:
        def __init__(self, ev_id: UUID):
            self.id = ev_id
            self.title = ""
            self.summary = ""
            self.content = ""

    class _FakeEntityRepository:
        def __init__(self, _session):  # noqa: ANN001
            return

        def get_entities_by_ids(self, ids, *, tenant_id=None):  # noqa: ANN001
            want = {str(x) for x in (ids or [])}
            ents = [
                _Ent(UUID(int=1), "Seed", "Tool"),
                _Ent(UUID(int=2), "S", "Skill"),
                _Ent(UUID(int=3), "T", "Tool"),
            ]
            return [e for e in ents if str(e.id) in want]

    class _FakeEventRepository:
        def __init__(self, _session):  # noqa: ANN001
            return

        def find_events_by_entities(self, *_a, **_k):  # noqa: ANN001
            return [_Ev(UUID(int=100))]

        def get_entities_for_events(self, event_ids, *, tenant_id=None):  # noqa: ANN001
            # Event 100 links to seed entity + skill + tool.
            return {str(UUID(int=100)): [_Ent(UUID(int=1), "Seed", "Tool"), _Ent(UUID(int=2), "S", "Skill"), _Ent(UUID(int=3), "T", "Tool")]}

    class _FakeRelationRepository:
        def __init__(self, _session):  # noqa: ANN001
            return

    monkeypatch.setattr(expand_mod, "EntityRepository", _FakeEntityRepository, raising=True)
    monkeypatch.setattr(expand_mod, "EventRepository", _FakeEventRepository, raising=True)
    monkeypatch.setattr(expand_mod, "RelationRepository", _FakeRelationRepository, raising=True)

    recall_result = RecallResult(
        query_vector=[0.0],
        key_final=[{"entity_id": str(UUID(int=1)), "name": "Seed", "type": "Tool", "weight": 1.0}],
        event_ids=[],
        clues=[],
        key_weights={str(UUID(int=1)): 1.0},
        event_scores={},
        relation_debug={"enabled": False},
    )

    cfg = SearchConfig(
        query="q",
        tenant_id=UUID(int=1),
        relation_expansion_enabled=False,
        include_skill_entities=True,
    )
    cfg.expand.max_hops = 1
    out = await ExpandSearcher().expand(cfg, recall_result)
    assert {str(e.get("type")) for e in (out.key_final or [])} == {"Tool", "Skill"}

    cfg2 = SearchConfig(
        query="q",
        tenant_id=UUID(int=1),
        relation_expansion_enabled=False,
        include_skill_entities=False,
    )
    cfg2.expand.max_hops = 1
    out2 = await ExpandSearcher().expand(cfg2, recall_result)
    assert {str(e.get("type")) for e in (out2.key_final or [])} == {"Tool"}

