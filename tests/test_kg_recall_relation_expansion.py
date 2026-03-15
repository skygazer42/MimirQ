from __future__ import annotations

import asyncio
from uuid import UUID

import pytest


@pytest.mark.asyncio
async def test_kg_recall_relation_expansion_adds_events(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.kg.search.recall as recall_mod
    from app.rag.kg.search.config import SearchConfig
    from app.rag.kg.search.recall import RecallSearcher

    # Enable relation expansion (safe opt-in feature).
    monkeypatch.setattr(recall_mod.settings, "KG_RELATION_ENABLED", True, raising=False)
    monkeypatch.setattr(recall_mod.settings, "KG_SEARCH_RELATION_EXPANSION_ENABLED", True, raising=False)
    monkeypatch.setattr(recall_mod.settings, "KG_SEARCH_RELATION_MAX_NEIGHBORS", 10, raising=False)
    monkeypatch.setattr(recall_mod.settings, "KG_SEARCH_RELATION_MAX_EDGES", 50, raising=False)
    monkeypatch.setattr(recall_mod.settings, "KG_SEARCH_RELATION_MIN_CONFIDENCE", 0.1, raising=False)
    monkeypatch.setattr(recall_mod.settings, "KG_SEARCH_RELATION_NEIGHBOR_WEIGHT_FACTOR", 1.0, raising=False)

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
            return [{"entity_id": str(UUID(int=10)), "name": "A", "type": "t", "similarity": 0.9}]

    class _Ev:
        def __init__(self, ev_id: UUID):
            self.id = ev_id
            self.content_vector = None

    class _Link:
        def __init__(self, entity_id: UUID):
            self.entity_id = entity_id

    class _FakeEventRepository:
        def __init__(self, _session):  # noqa: ANN001
            return

        def filter_entity_ids_in_documents(self, entity_ids, *, tenant_id, document_ids):  # noqa: ANN001
            assert entity_ids
            assert tenant_id
            assert document_ids
            return {UUID(int=10)}

        def search_events_by_entities(  # noqa: ANN001
            self,
            entity_ids,
            tenant_id,
            limit=50,
            document_ids=None,
            dataset_id=None,
            account_id=None,
        ):
            assert tenant_id
            assert limit > 0
            ids = {str(e) for e in (entity_ids or [])}
            if str(UUID(int=10)) in ids:
                return [UUID(int=100)]
            if str(UUID(int=11)) in ids:
                return [UUID(int=101)]
            return []

        def search_similar_by_content(self, *_a, **_k):  # noqa: ANN001
            return []

        def get_events_by_ids(self, event_ids, *_a, **_k):  # noqa: ANN001
            want = {str(x) for x in (event_ids or [])}
            out = []
            if str(UUID(int=100)) in want:
                out.append(_Ev(UUID(int=100)))
            if str(UUID(int=101)) in want:
                out.append(_Ev(UUID(int=101)))
            return out

        def get_event_entities(self, *_a, **_k):  # noqa: ANN001
            return {
                str(UUID(int=100)): [_Link(UUID(int=10))],
                str(UUID(int=101)): [_Link(UUID(int=11))],
            }

    class _Rel:
        def __init__(self):
            self.subject_entity_id = UUID(int=10)
            self.object_entity_id = UUID(int=11)
            self.predicate = "related_to"
            self.confidence = 0.9

    class _FakeRelationRepository:
        def __init__(self, _session):  # noqa: ANN001
            return

        def list_relations_for_entities(  # noqa: ANN001
            self,
            entity_ids,
            *,
            tenant_id,
            document_ids=None,
            dataset_id=None,
            account_id=None,
            min_confidence=None,
            allowed_predicates=None,
            limit=2000,
        ):
            assert entity_ids == [str(UUID(int=10))]
            assert tenant_id == UUID(int=1)
            assert document_ids == [UUID(int=2)]
            assert dataset_id is None
            assert account_id is None
            assert min_confidence == pytest.approx(0.1)
            assert allowed_predicates is None
            assert limit == 50
            return [_Rel()]

    monkeypatch.setattr(recall_mod, "EntityRepository", _FakeEntityRepository, raising=True)
    monkeypatch.setattr(recall_mod, "EventRepository", _FakeEventRepository, raising=True)
    monkeypatch.setattr(recall_mod, "RelationRepository", _FakeRelationRepository, raising=True)

    config = SearchConfig(query="q", tenant_id=UUID(int=1), document_ids=[UUID(int=2)])
    result = await RecallSearcher().search(config)

    assert set(result.event_ids) == {str(UUID(int=100)), str(UUID(int=101))}


@pytest.mark.asyncio
async def test_kg_recall_relation_expansion_can_be_forced_off(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.kg.search.recall as recall_mod
    from app.rag.kg.search.config import SearchConfig
    from app.rag.kg.search.recall import RecallSearcher

    # Enable relation expansion globally, but force it off per-call.
    monkeypatch.setattr(recall_mod.settings, "KG_RELATION_ENABLED", True, raising=False)
    monkeypatch.setattr(recall_mod.settings, "KG_SEARCH_RELATION_EXPANSION_ENABLED", True, raising=False)
    monkeypatch.setattr(recall_mod.settings, "KG_SEARCH_RELATION_MAX_NEIGHBORS", 10, raising=False)
    monkeypatch.setattr(recall_mod.settings, "KG_SEARCH_RELATION_MAX_EDGES", 50, raising=False)
    monkeypatch.setattr(recall_mod.settings, "KG_SEARCH_RELATION_MIN_CONFIDENCE", 0.1, raising=False)
    monkeypatch.setattr(recall_mod.settings, "KG_SEARCH_RELATION_NEIGHBOR_WEIGHT_FACTOR", 1.0, raising=False)

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
            return [{"entity_id": str(UUID(int=10)), "name": "A", "type": "t", "similarity": 0.9}]

    class _Ev:
        def __init__(self, ev_id: UUID):
            self.id = ev_id
            self.content_vector = None

    class _Link:
        def __init__(self, entity_id: UUID):
            self.entity_id = entity_id

    class _FakeEventRepository:
        def __init__(self, _session):  # noqa: ANN001
            return

        def filter_entity_ids_in_documents(self, entity_ids, *, tenant_id, document_ids):  # noqa: ANN001
            assert entity_ids
            assert tenant_id
            assert document_ids
            return {UUID(int=10)}

        def search_events_by_entities(  # noqa: ANN001
            self,
            entity_ids,
            tenant_id,
            limit=50,
            document_ids=None,
            dataset_id=None,
            account_id=None,
        ):
            assert tenant_id
            assert limit > 0
            ids = {str(e) for e in (entity_ids or [])}
            if str(UUID(int=10)) in ids:
                return [UUID(int=100)]
            if str(UUID(int=11)) in ids:
                return [UUID(int=101)]
            return []

        def search_similar_by_content(self, *_a, **_k):  # noqa: ANN001
            return []

        def get_events_by_ids(self, event_ids, *_a, **_k):  # noqa: ANN001
            want = {str(x) for x in (event_ids or [])}
            out = []
            if str(UUID(int=100)) in want:
                out.append(_Ev(UUID(int=100)))
            if str(UUID(int=101)) in want:
                out.append(_Ev(UUID(int=101)))
            return out

        def get_event_entities(self, *_a, **_k):  # noqa: ANN001
            return {
                str(UUID(int=100)): [_Link(UUID(int=10))],
                str(UUID(int=101)): [_Link(UUID(int=11))],
            }

    class _FakeRelationRepository:
        def __init__(self, _session):  # noqa: ANN001
            return

        def list_relations_for_entities(self, *_a, **_k):  # noqa: ANN001
            raise AssertionError("RelationRepository should not be called when forced off")

    monkeypatch.setattr(recall_mod, "EntityRepository", _FakeEntityRepository, raising=True)
    monkeypatch.setattr(recall_mod, "EventRepository", _FakeEventRepository, raising=True)
    monkeypatch.setattr(recall_mod, "RelationRepository", _FakeRelationRepository, raising=True)

    config = SearchConfig(
        query="q",
        tenant_id=UUID(int=1),
        document_ids=[UUID(int=2)],
        relation_expansion_enabled=False,
    )
    result = await RecallSearcher().search(config)

    assert result.relation_debug.get("enabled") is False
    assert set(result.event_ids) == {str(UUID(int=100))}


@pytest.mark.asyncio
async def test_kg_recall_relation_expansion_downweights_mention_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.kg.search.recall as recall_mod
    from app.rag.kg.search.config import SearchConfig
    from app.rag.kg.search.recall import RecallSearcher

    # Enable relation expansion (safe opt-in feature).
    monkeypatch.setattr(recall_mod.settings, "KG_RELATION_ENABLED", True, raising=False)
    monkeypatch.setattr(recall_mod.settings, "KG_SEARCH_RELATION_EXPANSION_ENABLED", True, raising=False)
    monkeypatch.setattr(recall_mod.settings, "KG_SEARCH_RELATION_MAX_NEIGHBORS", 1, raising=False)
    monkeypatch.setattr(recall_mod.settings, "KG_SEARCH_RELATION_MAX_EDGES", 50, raising=False)
    monkeypatch.setattr(recall_mod.settings, "KG_SEARCH_RELATION_MIN_CONFIDENCE", 0.1, raising=False)
    monkeypatch.setattr(recall_mod.settings, "KG_SEARCH_RELATION_NEIGHBOR_WEIGHT_FACTOR", 1.0, raising=False)

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
            return [{"entity_id": str(UUID(int=10)), "name": "A", "type": "t", "similarity": 0.9}]

    class _Ev:
        def __init__(self, ev_id: UUID):
            self.id = ev_id
            self.content_vector = None

    class _Link:
        def __init__(self, entity_id: UUID):
            self.entity_id = entity_id

    class _FakeEventRepository:
        def __init__(self, _session):  # noqa: ANN001
            return

        def filter_entity_ids_in_documents(self, entity_ids, *, tenant_id, document_ids):  # noqa: ANN001
            assert entity_ids
            assert tenant_id
            assert document_ids
            return {UUID(int=10)}

        def search_events_by_entities(  # noqa: ANN001
            self,
            entity_ids,
            tenant_id,
            limit=50,
            document_ids=None,
            dataset_id=None,
            account_id=None,
        ):
            assert tenant_id
            assert limit > 0
            ids = {str(e) for e in (entity_ids or [])}
            if str(UUID(int=10)) in ids:
                return [UUID(int=100)]
            if str(UUID(int=11)) in ids:
                return [UUID(int=101)]
            if str(UUID(int=12)) in ids:
                return [UUID(int=102)]
            return []

        def search_similar_by_content(self, *_a, **_k):  # noqa: ANN001
            return []

        def get_events_by_ids(self, event_ids, *_a, **_k):  # noqa: ANN001
            want = {str(x) for x in (event_ids or [])}
            out = []
            for uid in (UUID(int=100), UUID(int=101), UUID(int=102)):
                if str(uid) in want:
                    out.append(_Ev(uid))
            return out

        def get_event_entities(self, *_a, **_k):  # noqa: ANN001
            return {
                str(UUID(int=100)): [_Link(UUID(int=10))],
                str(UUID(int=101)): [_Link(UUID(int=11))],
                str(UUID(int=102)): [_Link(UUID(int=12))],
            }

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

        def list_relations_for_entities(  # noqa: ANN001
            self,
            entity_ids,
            *,
            tenant_id,
            document_ids=None,
            dataset_id=None,
            account_id=None,
            min_confidence=None,
            allowed_predicates=None,
            limit=2000,
        ):
            assert entity_ids == [str(UUID(int=10))]
            assert tenant_id == UUID(int=1)
            assert document_ids == [UUID(int=2)]
            assert min_confidence == pytest.approx(0.1)
            assert allowed_predicates is None
            assert limit == 50
            # Without downweighting, the "mention" edge would win due to higher confidence.
            # With downweighting, the "quote" edge should win and drive neighbor selection.
            return [
                _Rel(obj=UUID(int=11), conf=0.6, evidence_source="mention"),
                _Rel(obj=UUID(int=12), conf=0.55, evidence_source="quote"),
            ]

    monkeypatch.setattr(recall_mod, "EntityRepository", _FakeEntityRepository, raising=True)
    monkeypatch.setattr(recall_mod, "EventRepository", _FakeEventRepository, raising=True)
    monkeypatch.setattr(recall_mod, "RelationRepository", _FakeRelationRepository, raising=True)

    config = SearchConfig(query="q", tenant_id=UUID(int=1), document_ids=[UUID(int=2)])
    result = await RecallSearcher().search(config)

    # Expect the quote-grounded edge to dominate after mention penalty.
    assert set(result.event_ids) == {str(UUID(int=100)), str(UUID(int=102))}
