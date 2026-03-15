from __future__ import annotations

from uuid import UUID

import pytest

from tests.helpers.async_utils import yield_control


@pytest.mark.asyncio
async def test_kg_recall_relation_expansion_ignores_unknown_predicates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.kg.search.recall as recall_mod
    from app.rag.kg.search.config import SearchConfig
    from app.rag.kg.search.recall import RecallSearcher

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
        await yield_control()
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

    calls = {"seed": 0, "neighbor": 0}

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
            if str(UUID(int=11)) in ids:
                calls["neighbor"] += 1
                return [UUID(int=101)]
            calls["seed"] += 1
            return [UUID(int=100)]

        def search_similar_by_content(self, *_a, **_k):  # noqa: ANN001
            return []

        def get_events_by_ids(self, *_a, **_k):  # noqa: ANN001
            return [_Ev(UUID(int=100))]

        def get_event_entities(self, *_a, **_k):  # noqa: ANN001
            return {str(UUID(int=100)): [_Link(UUID(int=10))]}

    class _Rel:
        def __init__(self):
            self.subject_entity_id = UUID(int=10)
            self.object_entity_id = UUID(int=11)
            self.predicate = "unknown"
            self.confidence = 0.9

    class _FakeRelationRepository:
        def __init__(self, _session):  # noqa: ANN001
            return

        def list_relations_for_entities(self, *_a, **_k):  # noqa: ANN001
            return [_Rel()]

    monkeypatch.setattr(recall_mod, "EntityRepository", _FakeEntityRepository, raising=True)
    monkeypatch.setattr(recall_mod, "EventRepository", _FakeEventRepository, raising=True)
    monkeypatch.setattr(recall_mod, "RelationRepository", _FakeRelationRepository, raising=True)

    config = SearchConfig(query="q", tenant_id=UUID(int=1), document_ids=[UUID(int=2)])
    result = await RecallSearcher().search(config)

    assert calls["seed"] == 1
    assert calls["neighbor"] == 0
    assert result.event_ids == [str(UUID(int=100))]

