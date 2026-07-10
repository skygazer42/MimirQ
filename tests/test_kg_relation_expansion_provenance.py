
from uuid import UUID

import pytest

from tests.helpers.async_utils import yield_control


@pytest.mark.asyncio
async def test_kg_recall_relation_expansion_clues_include_provenance_and_confidence_bucket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.kg.search.recall as recall_mod
    from app.rag.kg.search.config import SearchConfig
    from app.rag.kg.search.recall import RecallSearcher

    # Enable relation expansion (safe opt-in feature).
    monkeypatch.setattr(recall_mod.settings, "KG_RELATION_ENABLED", True, raising=False)
    monkeypatch.setattr(recall_mod.settings, "KG_SEARCH_RELATION_EXPANSION_ENABLED", True, raising=False)
    monkeypatch.setattr(recall_mod.settings, "KG_SEARCH_RELATION_MAX_NEIGHBORS", 10, raising=False)

    # Cap settings should flow into repository call.
    monkeypatch.setattr(recall_mod.settings, "KG_SEARCH_RELATION_MAX_EDGES", 2, raising=False)
    monkeypatch.setattr(recall_mod.settings, "KG_SEARCH_RELATION_MIN_CONFIDENCE", 0.0, raising=False)
    monkeypatch.setattr(recall_mod.settings, "KG_SEARCH_RELATION_NEIGHBOR_WEIGHT_FACTOR", 1.0, raising=False)

    # Non-default thresholds: if the implementation ignores settings and uses defaults,
    # confidence=0.7 would bucket to "high". With mid_max=0.85, it should be "mid".
    monkeypatch.setattr(recall_mod.settings, "KG_SEARCH_RELATION_CONF_BUCKET_LOW_MAX", 0.2, raising=False)
    monkeypatch.setattr(recall_mod.settings, "KG_SEARCH_RELATION_CONF_BUCKET_MID_MAX", 0.85, raising=False)

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

    rel_id = UUID(int=500)
    rel_doc_id = UUID(int=2)
    rel_chunk_id = UUID(int=600)
    rel_event_id = UUID(int=700)

    class _Rel:
        def __init__(self):
            self.id = rel_id
            self.subject_entity_id = UUID(int=10)
            self.object_entity_id = UUID(int=11)
            self.predicate = "related_to"
            self.confidence = 0.7
            self.references = {"evidence_source": "Mention"}  # should be normalized to "mention"
            self.document_id = rel_doc_id
            self.chunk_id = rel_chunk_id
            self.event_id = rel_event_id

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
            assert min_confidence is None
            assert allowed_predicates is None
            assert limit == 2
            return [_Rel()]

    monkeypatch.setattr(recall_mod, "EntityRepository", _FakeEntityRepository, raising=True)
    monkeypatch.setattr(recall_mod, "EventRepository", _FakeEventRepository, raising=True)
    monkeypatch.setattr(recall_mod, "RelationRepository", _FakeRelationRepository, raising=True)

    config = SearchConfig(query="q", tenant_id=UUID(int=1), document_ids=[UUID(int=2)])
    result = await RecallSearcher().search(config)

    rel_clues = [c for c in (result.clues or []) if (c.get("metadata") or {}).get("method") == "relation_expansion"]
    assert rel_clues, "expected at least one relation_expansion clue"

    md = rel_clues[0].get("metadata") or {}
    assert md.get("evidence_source") == "mention"
    assert md.get("confidence_bucket") == "mid"
    assert md.get("relation_id") == str(rel_id)
    assert md.get("relation_document_id") == str(rel_doc_id)
    assert md.get("relation_chunk_id") == str(rel_chunk_id)
    assert md.get("relation_event_id") == str(rel_event_id)

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

    monkeypatch.setattr(expand_mod.settings, "KG_SEARCH_RELATION_MAX_NEIGHBORS", 1, raising=False)
    monkeypatch.setattr(expand_mod.settings, "KG_SEARCH_RELATION_MAX_EDGES", 2, raising=False)
    monkeypatch.setattr(expand_mod.settings, "KG_SEARCH_RELATION_MIN_CONFIDENCE", 0.0, raising=False)
    monkeypatch.setattr(expand_mod.settings, "KG_SEARCH_RELATION_NEIGHBOR_WEIGHT_FACTOR", 1.0, raising=False)
    monkeypatch.setattr(expand_mod.settings, "KG_SEARCH_RELATION_CONF_BUCKET_LOW_MAX", 0.2, raising=False)
    monkeypatch.setattr(expand_mod.settings, "KG_SEARCH_RELATION_CONF_BUCKET_MID_MAX", 0.85, raising=False)

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
                _Ent(UUID(int=11), "Neighbor", "Tool"),
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
            return out[: int(limit)]

        def get_entities_for_events(self, event_ids, *, tenant_id=None):  # noqa: ANN001
            want = {str(x) for x in (event_ids or [])}
            out: dict[str, list[_Ent]] = {}
            if str(UUID(int=100)) in want:
                out[str(UUID(int=100))] = [_Ent(UUID(int=10), "Seed", "Tool")]
            if str(UUID(int=101)) in want:
                out[str(UUID(int=101))] = [_Ent(UUID(int=11), "Neighbor", "Tool")]
            return out

    rel_id = UUID(int=501)
    rel_doc_id = UUID(int=2)
    rel_chunk_id = UUID(int=601)
    rel_event_id = UUID(int=701)

    class _Rel:
        def __init__(self):
            self.id = rel_id
            self.subject_entity_id = UUID(int=10)
            self.object_entity_id = UUID(int=11)
            self.predicate = "related_to"
            self.confidence = 0.7
            self.references = {"evidence_source": "Quote"}
            self.document_id = rel_doc_id
            self.chunk_id = rel_chunk_id
            self.event_id = rel_event_id

    class _FakeRelationRepository:
        def __init__(self, _session):  # noqa: ANN001
            return

        def list_relations_for_entities(self, entity_ids, *, tenant_id, limit=2000, **_k):  # noqa: ANN001
            assert entity_ids == [str(UUID(int=10))]
            assert tenant_id == UUID(int=1)
            assert limit == 2
            return [_Rel()]

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

    rel_clues = [c for c in (out.clues or []) if (c.get("metadata") or {}).get("method") == "relation_expansion"]
    assert rel_clues, "expected at least one relation_expansion clue"

    md = rel_clues[0].get("metadata") or {}
    assert md.get("evidence_source") == "quote"
    assert md.get("confidence_bucket") == "mid"
    assert md.get("relation_id") == str(rel_id)
    assert md.get("relation_document_id") == str(rel_doc_id)
    assert md.get("relation_chunk_id") == str(rel_chunk_id)
    assert md.get("relation_event_id") == str(rel_event_id)

