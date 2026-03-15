from __future__ import annotations

from uuid import UUID

import pytest


@pytest.mark.asyncio
async def test_kg_recall_uses_graph_embeddings_when_vector_recall_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Wave16: when vector recall is disabled/unavailable, KG recall can still expand entity candidates
    via offline/deterministic graph embeddings.
    """
    from app.core import config as config_mod

    monkeypatch.setattr(config_mod.settings, "KG_ENABLED", True, raising=False)
    monkeypatch.setattr(config_mod.settings, "KG_SEARCH_VECTOR_RECALL_ENABLED", False, raising=False)
    monkeypatch.setattr(config_mod.settings, "KG_SEARCH_GRAPH_EMBEDDINGS_ENABLED", True, raising=False)

    from app.rag.kg.search.config import SearchConfig
    from app.rag.kg.search.recall import RecallSearcher

    tenant_id = UUID(int=1)
    alias_entity_id = UUID(int=123)
    graph_entity_id = UUID(int=124)
    event_id = UUID(int=456)

    alias_hit = {
        "entity_id": str(alias_entity_id),
        "name": "ALIAS_SEED",
        "type": "Tech",
        "similarity": 1.0,
        "tenant_id": str(tenant_id),
        "method": "alias_match",
    }

    import app.rag.kg.search.recall as recall_mod

    # No DB connections in unit tests.
    monkeypatch.setattr(recall_mod, "get_session", lambda: type("_S", (), {"close": lambda _self: None})(), raising=True)

    # Seed entities come from aliases.
    monkeypatch.setattr(recall_mod.AliasRepository, "match_aliases", lambda *_a, **_k: [alias_hit], raising=True)

    # Vector entity recall should be disabled entirely.
    monkeypatch.setattr(
        recall_mod.EntityRepository,
        "search_similar",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("vector entity recall should be disabled")),
        raising=True,
    )
    monkeypatch.setattr(
        recall_mod.EventRepository,
        "search_similar_by_content",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("vector event recall should be disabled")),
        raising=True,
    )

    # Graph embedding recall: force a deterministic hit without running the full embedding algorithm.
    called = {"n": 0}

    def _fake_graph_hits(*_a, **_k):
        called["n"] += 1
        return [
            {
                "node_key": f"ent:{graph_entity_id}",
                "similarity": 0.8,
                "seed_node_key": f"ent:{alias_entity_id}",
            }
        ]

    monkeypatch.setattr(
        recall_mod.graph_embeddings_mod,
        "recall_similar_entity_nodes",
        _fake_graph_hits,
        raising=True,
    )

    # Provide entity details for the graph-recalled entity id.
    class _Ent:
        def __init__(self) -> None:
            self.id = graph_entity_id
            self.name = "GRAPH_RECALLED"
            self.type = "Tech"

    monkeypatch.setattr(
        recall_mod.EntityRepository,
        "get_entities_by_ids",
        lambda *_a, **_k: [_Ent()],
        raising=True,
    )

    # Scope trimming: both entities are allowed.
    monkeypatch.setattr(
        recall_mod.EventRepository,
        "filter_entity_ids_in_documents",
        lambda *_a, **_k: {alias_entity_id, graph_entity_id},
        raising=True,
    )

    # Minimal event plumbing for steps 2/5/6/7.
    monkeypatch.setattr(recall_mod.EventRepository, "search_events_by_entities", lambda *_a, **_k: [event_id], raising=True)

    class _Ev:
        def __init__(self) -> None:
            self.id = event_id
            self.title = "t"
            self.summary = "s"
            self.content = "c"
            self.content_vector = None

    class _Link:
        def __init__(self, entity_id: UUID) -> None:
            self.entity_id = entity_id

    monkeypatch.setattr(recall_mod.EventRepository, "get_events_by_ids", lambda *_a, **_k: [_Ev()], raising=True)
    monkeypatch.setattr(
        recall_mod.EventRepository,
        "get_event_entities",
        lambda *_a, **_k: {str(event_id): [_Link(alias_entity_id), _Link(graph_entity_id)]},
        raising=True,
    )

    searcher = RecallSearcher()
    monkeypatch.setattr(
        searcher.processor,
        "generate_embedding",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("generate_embedding should not be called")),
        raising=True,
    )

    cfg = SearchConfig(query="What is ALIAS_SEED?", tenant_id=tenant_id, document_ids=[UUID(int=9)])
    out = await searcher.search(cfg)

    assert called["n"] >= 1, "expected graph embedding recall to be invoked"
    got_ids = {str(e.get("entity_id")) for e in (out.key_final or [])}
    assert str(alias_entity_id) in got_ids
    assert str(graph_entity_id) in got_ids

