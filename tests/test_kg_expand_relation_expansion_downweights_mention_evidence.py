from __future__ import annotations

from uuid import UUID

import pytest


@pytest.mark.asyncio
async def test_kg_expand_relation_expansion_downweights_mention_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.kg.search.expand as expand_mod
    from app.rag.kg.search.config import SearchConfig
    from app.rag.kg.search.expand import ExpandSearcher
    from app.rag.kg.search.recall import RecallResult

    # Relation expansion uses settings for candidate limits/weights even when forced on per-call.
    monkeypatch.setattr(expand_mod.settings, "KG_SEARCH_RELATION_MAX_NEIGHBORS", 1, raising=False)
    monkeypatch.setattr(expand_mod.settings, "KG_SEARCH_RELATION_MAX_EDGES", 50, raising=False)
    monkeypatch.setattr(expand_mod.settings, "KG_SEARCH_RELATION_MIN_CONFIDENCE", 0.1, raising=False)
    monkeypatch.setattr(expand_mod.settings, "KG_SEARCH_RELATION_NEIGHBOR_WEIGHT_FACTOR", 1.0, raising=False)

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
                _Ent(UUID(int=10), "Seed", "Tool"),
                _Ent(UUID(int=11), "MentionNeighbor", "Tool"),
                _Ent(UUID(int=12), "QuoteNeighbor", "Tool"),
            ]
            return [e for e in ents if str(e.id) in want]

    class _FakeEventRepository:
        def __init__(self, _session):  # noqa: ANN001
            return

        def find_events_by_entities(self, entity_ids, *, tenant_id=None, limit=50, **_k):  # noqa: ANN001
            ids = {str(x) for x in (entity_ids or [])}
            out = []
            if str(UUID(int=10)) in ids:
                out.append(_Ev(UUID(int=100)))
            if str(UUID(int=11)) in ids:
                out.append(_Ev(UUID(int=101)))
            if str(UUID(int=12)) in ids:
                out.append(_Ev(UUID(int=102)))
            return out[: int(limit)]

        def get_entities_for_events(self, event_ids, *, tenant_id=None):  # noqa: ANN001
            want = {str(x) for x in (event_ids or [])}
            out: dict[str, list[_Ent]] = {}
            if str(UUID(int=100)) in want:
                out[str(UUID(int=100))] = [_Ent(UUID(int=10), "Seed", "Tool")]
            if str(UUID(int=101)) in want:
                out[str(UUID(int=101))] = [_Ent(UUID(int=11), "MentionNeighbor", "Tool")]
            if str(UUID(int=102)) in want:
                out[str(UUID(int=102))] = [_Ent(UUID(int=12), "QuoteNeighbor", "Tool")]
            return out

    class _Rel:
        def __init__(self, *, obj: UUID, conf: float, evidence_source: str):
            self.subject_entity_id = UUID(int=10)
            self.object_entity_id = obj
            self.predicate = "related_to"
            self.confidence = conf
            self.references = {"evidence_source": evidence_source}

    class _FakeRelationRepository:
        def __init__(self, _session):  # noqa: ANN001
            return

        def list_relations_for_entities(self, entity_ids, *, tenant_id, limit=2000, **_k):  # noqa: ANN001
            assert entity_ids == [str(UUID(int=10))]
            assert tenant_id == UUID(int=1)
            assert limit == 50
            return [
                _Rel(obj=UUID(int=11), conf=0.6, evidence_source="mention"),
                _Rel(obj=UUID(int=12), conf=0.55, evidence_source="quote"),
            ]

    monkeypatch.setattr(expand_mod, "EntityRepository", _FakeEntityRepository, raising=True)
    monkeypatch.setattr(expand_mod, "EventRepository", _FakeEventRepository, raising=True)
    monkeypatch.setattr(expand_mod, "RelationRepository", _FakeRelationRepository, raising=True)

    recall_result = RecallResult(
        query_vector=[0.0],
        key_final=[{"entity_id": str(UUID(int=10)), "name": "Seed", "type": "Tool", "weight": 1.0}],
        event_ids=[],
        clues=[],
        key_weights={str(UUID(int=10)): 1.0},
        event_scores={},
        relation_debug={"enabled": True},
    )

    cfg = SearchConfig(
        query="q",
        tenant_id=UUID(int=1),
        relation_expansion_enabled=True,
        include_skill_entities=True,
    )
    cfg.expand.max_hops = 1
    cfg.expand.entities_per_hop = 1
    cfg.expand.min_events_per_hop = 1

    out = await ExpandSearcher().expand(cfg, recall_result)

    # Expect the quote-grounded edge to dominate after mention penalty.
    assert set(out.event_ids) == {str(UUID(int=100)), str(UUID(int=102))}

