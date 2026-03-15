from __future__ import annotations

from uuid import UUID

import pytest

from tests.helpers.async_utils import yield_control


@pytest.mark.asyncio
async def test_kg_recall_expands_query_via_entity_aliases(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Wave15: KG recall should incorporate human-governed aliases.

    - Alias matches should be added as high-confidence key entities
    - Canonical names should be appended to the embedding query (bounded)
    """
    from app.core import config as config_mod

    # KG search runs behind KG_ENABLED.
    monkeypatch.setattr(config_mod.settings, "KG_ENABLED", True, raising=False)

    from app.rag.kg.search.config import SearchConfig
    from app.rag.kg.search.recall import RecallSearcher

    alias_entity_id = UUID(int=123)
    hit = {
        "entity_id": str(alias_entity_id),
        "name": "Retrieval-Augmented Generation",
        "type": "Tech",
        "similarity": 1.0,
        "tenant_id": str(UUID(int=1)),
        "method": "alias_match",
    }

    # Patch alias lookup to return a deterministic hit.
    import app.rag.kg.search.recall as recall_mod

    monkeypatch.setattr(recall_mod.AliasRepository, "match_aliases", lambda *_a, **_k: [hit], raising=True)
    # Avoid DB connections in unit tests.
    monkeypatch.setattr(recall_mod, "get_session", lambda: type("_S", (), {"close": lambda _self: None})(), raising=True)

    # Prevent Milvus and DB IO: patch repositories to return empty candidates/events.
    monkeypatch.setattr(recall_mod.EntityRepository, "search_similar", lambda *_a, **_k: [], raising=True)
    monkeypatch.setattr(
        recall_mod.EventRepository,
        "filter_entity_ids_in_documents",
        lambda *_a, **_k: {alias_entity_id},
        raising=True,
    )
    monkeypatch.setattr(recall_mod.EventRepository, "search_events_by_entities", lambda *_a, **_k: [], raising=True)
    monkeypatch.setattr(recall_mod.EventRepository, "search_similar_by_content", lambda *_a, **_k: [], raising=True)
    monkeypatch.setattr(recall_mod.EventRepository, "get_events_by_ids", lambda *_a, **_k: [], raising=True)
    monkeypatch.setattr(recall_mod.EventRepository, "get_event_entities", lambda *_a, **_k: {}, raising=True)

    expanded_queries: list[str] = []

    async def _fake_embed(text: str) -> list[float]:
        await yield_control()
        expanded_queries.append(text)
        return [0.0, 0.0, 0.0]

    searcher = RecallSearcher()
    monkeypatch.setattr(searcher.processor, "generate_embedding", _fake_embed, raising=True)

    cfg = SearchConfig(query="What is RAG?", tenant_id=UUID(int=1), document_ids=[UUID(int=9)])
    out = await searcher.search(cfg)

    assert expanded_queries, "generate_embedding should have been called"
    assert "Retrieval-Augmented Generation" in expanded_queries[0]
    assert out.key_final, "alias hit should become a key entity"
    assert out.key_final[0]["entity_id"] == str(alias_entity_id)


@pytest.mark.asyncio
async def test_kg_recall_alias_keys_require_evidence_for_relation_expansion(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Wave15 safety: if an entity key was introduced via alias match, relation expansion should
    only traverse evidence-anchored edges (avoid drift from ambiguous aliases).
    """
    from app.core import config as config_mod

    monkeypatch.setattr(config_mod.settings, "KG_ENABLED", True, raising=False)
    monkeypatch.setattr(config_mod.settings, "KG_SEARCH_RELATION_EXPANSION_ENABLED", True, raising=False)

    from app.rag.kg.search.config import SearchConfig
    from app.rag.kg.search.recall import RecallSearcher

    tenant_id = UUID(int=1)
    alias_entity_id = UUID(int=123)
    neighbor_entity_id = UUID(int=124)

    hit = {
        "entity_id": str(alias_entity_id),
        "name": "RAG",
        "type": "Tech",
        "similarity": 1.0,
        "tenant_id": str(tenant_id),
        "method": "alias_match",
    }

    import app.rag.kg.search.recall as recall_mod

    monkeypatch.setattr(recall_mod.AliasRepository, "match_aliases", lambda *_a, **_k: [hit], raising=True)
    monkeypatch.setattr(recall_mod, "get_session", lambda: type("_S", (), {"close": lambda _self: None})(), raising=True)
    monkeypatch.setattr(recall_mod.EntityRepository, "search_similar", lambda *_a, **_k: [], raising=True)
    monkeypatch.setattr(
        recall_mod.EventRepository,
        "filter_entity_ids_in_documents",
        lambda *_a, **_k: {alias_entity_id},
        raising=True,
    )
    monkeypatch.setattr(recall_mod.EventRepository, "search_events_by_entities", lambda *_a, **_k: [], raising=True)
    monkeypatch.setattr(recall_mod.EventRepository, "search_similar_by_content", lambda *_a, **_k: [], raising=True)
    monkeypatch.setattr(recall_mod.EventRepository, "get_events_by_ids", lambda *_a, **_k: [], raising=True)
    monkeypatch.setattr(recall_mod.EventRepository, "get_event_entities", lambda *_a, **_k: {}, raising=True)

    class _Rel:
        def __init__(self) -> None:
            self.subject_entity_id = alias_entity_id
            self.object_entity_id = neighbor_entity_id
            self.predicate = "related_to"
            self.confidence = 0.9
            self.references = None  # no evidence_quote -> should be skipped for alias-driven expansion

    monkeypatch.setattr(
        recall_mod.RelationRepository,
        "list_relations_for_entities",
        lambda *_a, **_k: [_Rel()],
        raising=True,
    )

    async def _fake_embed(_text: str) -> list[float]:
        await yield_control()
        return [0.0, 0.0, 0.0]

    searcher = RecallSearcher()
    monkeypatch.setattr(searcher.processor, "generate_embedding", _fake_embed, raising=True)

    cfg = SearchConfig(
        query="RAG",
        tenant_id=tenant_id,
        document_ids=[UUID(int=9)],
        relation_expansion_enabled=True,
    )
    out = await searcher.search(cfg)

    # Relation expansion should have been enabled, but the non-evidence edge should be ignored.
    assert isinstance(out.relation_debug, dict)
    assert out.relation_debug.get("enabled") is True
    assert int(out.relation_debug.get("edges_used") or 0) == 0
