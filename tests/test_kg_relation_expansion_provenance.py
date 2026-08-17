from types import SimpleNamespace
from uuid import UUID

import pytest

from tests.helpers.async_utils import yield_control

_SEED_ENTITY_ID = UUID(int=10)
_NEIGHBOR_ENTITY_ID = UUID(int=11)
_SEED_EVENT_ID = UUID(int=100)
_NEIGHBOR_EVENT_ID = UUID(int=101)


async def _fake_generate_embedding(_self: object, _text: str) -> list[float]:
    await yield_control()
    return [0.0]


def _patch_recall_relation_settings(monkeypatch: pytest.MonkeyPatch, settings: object) -> None:
    monkeypatch.setattr(settings, "KG_RELATION_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "KG_SEARCH_RELATION_EXPANSION_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "KG_SEARCH_RELATION_MAX_NEIGHBORS", 10, raising=False)
    monkeypatch.setattr(settings, "KG_SEARCH_RELATION_MAX_EDGES", 2, raising=False)
    monkeypatch.setattr(settings, "KG_SEARCH_RELATION_MIN_CONFIDENCE", 0.0, raising=False)
    monkeypatch.setattr(settings, "KG_SEARCH_RELATION_NEIGHBOR_WEIGHT_FACTOR", 1.0, raising=False)
    monkeypatch.setattr(settings, "KG_SEARCH_RELATION_CONF_BUCKET_LOW_MAX", 0.2, raising=False)
    monkeypatch.setattr(settings, "KG_SEARCH_RELATION_CONF_BUCKET_MID_MAX", 0.85, raising=False)


def _patch_expand_relation_settings(monkeypatch: pytest.MonkeyPatch, settings: object) -> None:
    monkeypatch.setattr(settings, "KG_SEARCH_RELATION_MAX_NEIGHBORS", 1, raising=False)
    monkeypatch.setattr(settings, "KG_SEARCH_RELATION_MAX_EDGES", 2, raising=False)
    monkeypatch.setattr(settings, "KG_SEARCH_RELATION_MIN_CONFIDENCE", 0.0, raising=False)
    monkeypatch.setattr(settings, "KG_SEARCH_RELATION_NEIGHBOR_WEIGHT_FACTOR", 1.0, raising=False)
    monkeypatch.setattr(settings, "KG_SEARCH_RELATION_CONF_BUCKET_LOW_MAX", 0.2, raising=False)
    monkeypatch.setattr(settings, "KG_SEARCH_RELATION_CONF_BUCKET_MID_MAX", 0.85, raising=False)


class _FakeKGSession:
    def close(self) -> None:
        return


class _RecallEntityRepository:
    def search_similar(
        self,
        *,
        query_vector: object,
        tenant_id: object,
        k: object,
        entity_type: object = None,
    ) -> list[dict[str, object]]:
        assert query_vector
        assert tenant_id
        assert k
        assert entity_type is None
        return [{"entity_id": str(_SEED_ENTITY_ID), "name": "A", "type": "t", "similarity": 0.9}]


class _RecallEventRepository:
    def filter_entity_ids_in_documents(
        self,
        entity_ids: object,
        *,
        tenant_id: object,
        document_ids: object,
    ) -> set[UUID]:
        assert entity_ids
        assert tenant_id
        assert document_ids
        return {_SEED_ENTITY_ID}

    def search_events_by_entities(
        self,
        entity_ids: object,
        tenant_id: object,
        limit: int = 50,
        document_ids: object = None,
        dataset_id: object = None,
        account_id: object = None,
    ) -> list[UUID]:
        assert tenant_id
        assert limit > 0
        assert dataset_id is None
        assert account_id is None
        ids = {str(entity_id) for entity_id in (entity_ids or [])}
        if str(_SEED_ENTITY_ID) in ids:
            return [_SEED_EVENT_ID]
        if str(_NEIGHBOR_ENTITY_ID) in ids:
            return [_NEIGHBOR_EVENT_ID]
        return []

    def search_similar_by_content(self, *_args: object, **_kwargs: object) -> list[object]:
        return []

    def get_events_by_ids(
        self,
        event_ids: object,
        *_args: object,
        **_kwargs: object,
    ) -> list[SimpleNamespace]:
        want = {str(event_id) for event_id in (event_ids or [])}
        events = []
        if str(_SEED_EVENT_ID) in want:
            events.append(SimpleNamespace(id=_SEED_EVENT_ID, content_vector=None))
        if str(_NEIGHBOR_EVENT_ID) in want:
            events.append(SimpleNamespace(id=_NEIGHBOR_EVENT_ID, content_vector=None))
        return events

    def get_event_entities(self, *_args: object, **_kwargs: object) -> dict[str, list[SimpleNamespace]]:
        return {
            str(_SEED_EVENT_ID): [SimpleNamespace(entity_id=_SEED_ENTITY_ID)],
            str(_NEIGHBOR_EVENT_ID): [SimpleNamespace(entity_id=_NEIGHBOR_ENTITY_ID)],
        }


class _RecallRelationRepository:
    def __init__(self, relation: SimpleNamespace) -> None:
        self.relation = relation

    def list_relations_for_entities(
        self,
        entity_ids: object,
        *,
        tenant_id: object,
        document_ids: object = None,
        dataset_id: object = None,
        account_id: object = None,
        min_confidence: object = None,
        allowed_predicates: object = None,
        limit: int = 2000,
    ) -> list[SimpleNamespace]:
        assert entity_ids == [str(_SEED_ENTITY_ID)]
        assert tenant_id == UUID(int=1)
        assert document_ids == [UUID(int=2)]
        assert dataset_id is None
        assert account_id is None
        assert min_confidence is None
        assert allowed_predicates is None
        assert limit == 2
        return [self.relation]


class _ExpandEntityRepository:
    def get_entities_by_ids(self, ids: object, *, tenant_id: object = None) -> list[SimpleNamespace]:
        want = {str(entity_id) for entity_id in (ids or [])}
        entities = [
            SimpleNamespace(id=_SEED_ENTITY_ID, name="Seed", type="Tool"),
            SimpleNamespace(id=_NEIGHBOR_ENTITY_ID, name="Neighbor", type="Tool"),
        ]
        return [entity for entity in entities if str(entity.id) in want]


class _ExpandEventRepository:
    def find_events_by_entities(
        self,
        entity_ids: object,
        *,
        tenant_id: object = None,
        limit: int = 50,
        **_kwargs: object,
    ) -> list[SimpleNamespace]:
        ids = {str(entity_id) for entity_id in (entity_ids or [])}
        events = []
        if str(_SEED_ENTITY_ID) in ids:
            events.append(SimpleNamespace(id=_SEED_EVENT_ID, title="", summary="", content=""))
        if str(_NEIGHBOR_ENTITY_ID) in ids:
            events.append(SimpleNamespace(id=_NEIGHBOR_EVENT_ID, title="", summary="", content=""))
        return events[: int(limit)]

    def get_entities_for_events(
        self,
        event_ids: object,
        *,
        tenant_id: object = None,
    ) -> dict[str, list[SimpleNamespace]]:
        want = {str(event_id) for event_id in (event_ids or [])}
        entities: dict[str, list[SimpleNamespace]] = {}
        if str(_SEED_EVENT_ID) in want:
            entities[str(_SEED_EVENT_ID)] = [SimpleNamespace(id=_SEED_ENTITY_ID, name="Seed", type="Tool")]
        if str(_NEIGHBOR_EVENT_ID) in want:
            entities[str(_NEIGHBOR_EVENT_ID)] = [SimpleNamespace(id=_NEIGHBOR_ENTITY_ID, name="Neighbor", type="Tool")]
        return entities


class _ExpandRelationRepository:
    def __init__(self, relation: SimpleNamespace) -> None:
        self.relation = relation

    def list_relations_for_entities(
        self,
        entity_ids: object,
        *,
        tenant_id: object,
        limit: int = 2000,
        **_kwargs: object,
    ) -> list[SimpleNamespace]:
        assert entity_ids == [str(_SEED_ENTITY_ID)]
        assert tenant_id == UUID(int=1)
        assert limit == 2
        return [self.relation]


def _assert_relation_clue_metadata(
    clue_container: object,
    *,
    evidence_source: str,
    relation_id: UUID,
    document_id: UUID,
    chunk_id: UUID,
    event_id: UUID,
) -> None:
    rel_clues = [
        clue
        for clue in (clue_container.clues or [])
        if (clue.get("metadata") or {}).get("method") == "relation_expansion"
    ]
    assert rel_clues, "expected at least one relation_expansion clue"

    metadata = rel_clues[0].get("metadata") or {}
    assert metadata.get("evidence_source") == evidence_source
    assert metadata.get("confidence_bucket") == "mid"
    assert metadata.get("relation_id") == str(relation_id)
    assert metadata.get("relation_document_id") == str(document_id)
    assert metadata.get("relation_chunk_id") == str(chunk_id)
    assert metadata.get("relation_event_id") == str(event_id)


@pytest.mark.asyncio
async def test_kg_recall_relation_expansion_clues_include_provenance_and_confidence_bucket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.kg.search.recall as recall_mod
    from app.rag.kg.search.config import SearchConfig
    from app.rag.kg.search.recall import RecallSearcher

    _patch_recall_relation_settings(monkeypatch, recall_mod.settings)
    monkeypatch.setattr(recall_mod, "get_session", lambda: _FakeKGSession(), raising=True)
    monkeypatch.setattr(recall_mod.DocumentProcessor, "generate_embedding", _fake_generate_embedding, raising=True)
    monkeypatch.setattr(recall_mod, "EntityRepository", lambda _session: _RecallEntityRepository(), raising=True)
    monkeypatch.setattr(recall_mod, "EventRepository", lambda _session: _RecallEventRepository(), raising=True)

    relation = SimpleNamespace(
        id=UUID(int=500),
        subject_entity_id=_SEED_ENTITY_ID,
        object_entity_id=_NEIGHBOR_ENTITY_ID,
        predicate="related_to",
        confidence=0.7,
        references={"evidence_source": "Mention"},
        document_id=UUID(int=2),
        chunk_id=UUID(int=600),
        event_id=UUID(int=700),
    )
    monkeypatch.setattr(
        recall_mod,
        "RelationRepository",
        lambda _session: _RecallRelationRepository(relation),
        raising=True,
    )

    config = SearchConfig(query="q", tenant_id=UUID(int=1), document_ids=[UUID(int=2)])
    result = await RecallSearcher().search(config)

    _assert_relation_clue_metadata(
        result,
        evidence_source="mention",
        relation_id=relation.id,
        document_id=relation.document_id,
        chunk_id=relation.chunk_id,
        event_id=relation.event_id,
    )

    dbg = result.relation_debug or {}
    assert dbg.get("enabled") is True
    assert dbg.get("conf_bucket_low_max") == pytest.approx(0.2)
    assert dbg.get("conf_bucket_mid_max") == pytest.approx(0.85)
    assert (dbg.get("confidence_bucket_hist") or {}).get("mid") == 1


@pytest.mark.asyncio
async def test_kg_expand_relation_expansion_clues_include_provenance_and_confidence_bucket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.kg.search.expand as expand_mod
    from app.rag.kg.search.config import SearchConfig
    from app.rag.kg.search.expand import ExpandSearcher
    from app.rag.kg.search.recall import RecallResult

    _patch_expand_relation_settings(monkeypatch, expand_mod.settings)
    monkeypatch.setattr(expand_mod, "get_session", lambda: _FakeKGSession(), raising=True)
    monkeypatch.setattr(expand_mod, "EntityRepository", lambda _session: _ExpandEntityRepository(), raising=True)
    monkeypatch.setattr(expand_mod, "EventRepository", lambda _session: _ExpandEventRepository(), raising=True)

    relation = SimpleNamespace(
        id=UUID(int=501),
        subject_entity_id=_SEED_ENTITY_ID,
        object_entity_id=_NEIGHBOR_ENTITY_ID,
        predicate="related_to",
        confidence=0.7,
        references={"evidence_source": "Quote"},
        document_id=UUID(int=2),
        chunk_id=UUID(int=601),
        event_id=UUID(int=701),
    )
    monkeypatch.setattr(
        expand_mod,
        "RelationRepository",
        lambda _session: _ExpandRelationRepository(relation),
        raising=True,
    )

    recall_result = RecallResult(
        query_vector=[0.0],
        key_final=[{"entity_id": str(_SEED_ENTITY_ID), "name": "Seed", "type": "Tool", "weight": 1.0}],
        event_ids=[],
        clues=[],
        key_weights={str(_SEED_ENTITY_ID): 1.0},
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

    _assert_relation_clue_metadata(
        out,
        evidence_source="quote",
        relation_id=relation.id,
        document_id=relation.document_id,
        chunk_id=relation.chunk_id,
        event_id=relation.event_id,
    )
