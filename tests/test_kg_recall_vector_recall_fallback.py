from __future__ import annotations

from uuid import UUID

import pytest

from tests.helpers.async_utils import yield_control


@pytest.mark.asyncio
async def test_kg_recall_skips_embeddings_when_vector_recall_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Wave16: CI/offline mode should be able to run KG recall without embeddings/Milvus.

    When KG_SEARCH_VECTOR_RECALL_ENABLED=false:
    - Recall must not call the embedding provider.
    - Recall must still surface alias-matched entities and corresponding events.
    """
    from app.core import config as config_mod

    monkeypatch.setattr(config_mod.settings, "KG_ENABLED", True, raising=False)
    monkeypatch.setattr(config_mod.settings, "KG_SEARCH_VECTOR_RECALL_ENABLED", False, raising=False)

    from app.rag.kg.search.config import SearchConfig
    from app.rag.kg.search.recall import RecallSearcher

    tenant_id = UUID(int=1)
    alias_entity_id = UUID(int=123)
    event_id = UUID(int=456)

    hit = {
        "entity_id": str(alias_entity_id),
        "name": "CITOKENKGALPHA9B7C3E",
        "type": "Tech",
        "similarity": 1.0,
        "tenant_id": str(tenant_id),
        "method": "alias_match",
    }

    import app.rag.kg.search.recall as recall_mod

    # No DB connections in unit tests.
    monkeypatch.setattr(recall_mod, "get_session", lambda: type("_S", (), {"close": lambda _self: None})(), raising=True)

    monkeypatch.setattr(recall_mod.AliasRepository, "match_aliases", lambda *_a, **_k: [hit], raising=True)
    monkeypatch.setattr(recall_mod.EntityRepository, "search_similar", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("vector entity recall should be disabled")), raising=True)
    monkeypatch.setattr(recall_mod.EventRepository, "search_similar_by_content", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("vector event recall should be disabled")), raising=True)
    monkeypatch.setattr(
        recall_mod.EventRepository,
        "filter_entity_ids_in_documents",
        lambda *_a, **_k: {alias_entity_id},
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
        def __init__(self) -> None:
            self.entity_id = alias_entity_id

    monkeypatch.setattr(recall_mod.EventRepository, "get_events_by_ids", lambda *_a, **_k: [_Ev()], raising=True)
    monkeypatch.setattr(recall_mod.EventRepository, "get_event_entities", lambda *_a, **_k: {str(event_id): [_Link()]}, raising=True)

    searcher = RecallSearcher()
    monkeypatch.setattr(
        searcher.processor,
        "generate_embedding",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("generate_embedding should not be called")),
        raising=True,
    )

    cfg = SearchConfig(query="What is CITOKENKGALPHA9B7C3E?", tenant_id=tenant_id, document_ids=[UUID(int=9)])
    out = await searcher.search(cfg)

    assert out.query_vector == []
    assert out.key_final and out.key_final[0]["entity_id"] == str(alias_entity_id)
    assert str(event_id) in list(out.event_ids or [])


@pytest.mark.asyncio
async def test_kg_recall_falls_back_when_embedding_provider_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Wave16: even with vector recall enabled, failures to generate embeddings (or reach Milvus)
    must not hard-fail the whole recall stage when alias keys exist.
    """
    from app.core import config as config_mod

    monkeypatch.setattr(config_mod.settings, "KG_ENABLED", True, raising=False)
    monkeypatch.setattr(config_mod.settings, "KG_SEARCH_VECTOR_RECALL_ENABLED", True, raising=False)

    from app.rag.kg.search.config import SearchConfig
    from app.rag.kg.search.recall import RecallSearcher

    tenant_id = UUID(int=1)
    alias_entity_id = UUID(int=123)
    event_id = UUID(int=456)

    hit = {
        "entity_id": str(alias_entity_id),
        "name": "CITOKENKGALPHA9B7C3E",
        "type": "Tech",
        "similarity": 1.0,
        "tenant_id": str(tenant_id),
        "method": "alias_match",
    }

    import app.rag.kg.search.recall as recall_mod

    monkeypatch.setattr(recall_mod, "get_session", lambda: type("_S", (), {"close": lambda _self: None})(), raising=True)
    monkeypatch.setattr(recall_mod.AliasRepository, "match_aliases", lambda *_a, **_k: [hit], raising=True)
    monkeypatch.setattr(recall_mod.EntityRepository, "search_similar", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("should not call milvus when embedding fails")), raising=True)
    monkeypatch.setattr(recall_mod.EventRepository, "search_similar_by_content", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("should not call milvus when embedding fails")), raising=True)
    monkeypatch.setattr(
        recall_mod.EventRepository,
        "filter_entity_ids_in_documents",
        lambda *_a, **_k: {alias_entity_id},
        raising=True,
    )
    monkeypatch.setattr(recall_mod.EventRepository, "search_events_by_entities", lambda *_a, **_k: [event_id], raising=True)

    class _Ev:
        def __init__(self) -> None:
            self.id = event_id
            self.title = "t"
            self.summary = "s"
            self.content = "c"
            self.content_vector = None

    class _Link:
        def __init__(self) -> None:
            self.entity_id = alias_entity_id

    monkeypatch.setattr(recall_mod.EventRepository, "get_events_by_ids", lambda *_a, **_k: [_Ev()], raising=True)
    monkeypatch.setattr(recall_mod.EventRepository, "get_event_entities", lambda *_a, **_k: {str(event_id): [_Link()]}, raising=True)

    async def _boom(_text: str) -> list[float]:
        await yield_control()
        raise RuntimeError("no embedding provider")

    searcher = RecallSearcher()
    monkeypatch.setattr(searcher.processor, "generate_embedding", _boom, raising=True)

    cfg = SearchConfig(query="What is CITOKENKGALPHA9B7C3E?", tenant_id=tenant_id, document_ids=[UUID(int=9)])
    out = await searcher.search(cfg)

    assert out.query_vector == []
    assert out.key_final and out.key_final[0]["entity_id"] == str(alias_entity_id)
    assert str(event_id) in list(out.event_ids or [])


@pytest.mark.asyncio
async def test_kg_recall_uses_lexical_entities_when_embeddings_and_aliases_miss(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Dataset-scoped KG search must remain useful when the embedding provider is unavailable
    and no governed alias exists yet. The fallback still goes through scoped event lookup.
    """
    from app.core import config as config_mod

    monkeypatch.setattr(config_mod.settings, "KG_ENABLED", True, raising=False)
    monkeypatch.setattr(config_mod.settings, "KG_SEARCH_VECTOR_RECALL_ENABLED", True, raising=False)

    from app.rag.kg.search.config import SearchConfig
    from app.rag.kg.search.recall import RecallSearcher

    tenant_id = UUID(int=1)
    dataset_id = UUID(int=8)
    entity_id = UUID(int=123)
    event_id = UUID(int=456)

    hit = {
        "entity_id": str(entity_id),
        "name": "QUIC",
        "type": "protocol",
        "similarity": 1.0,
        "tenant_id": str(tenant_id),
        "method": "lexical_match",
    }

    import app.rag.kg.search.recall as recall_mod

    monkeypatch.setattr(recall_mod, "get_session", lambda: type("_S", (), {"close": lambda _self: None})(), raising=True)
    monkeypatch.setattr(recall_mod.AliasRepository, "match_aliases", lambda *_a, **_k: [], raising=True)
    monkeypatch.setattr(recall_mod.EntityRepository, "search_similar", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("should not call milvus when embedding fails")), raising=True)
    monkeypatch.setattr(recall_mod.EntityRepository, "search_lexical", lambda *_a, **_k: [hit], raising=True)
    monkeypatch.setattr(recall_mod.EventRepository, "search_events_lexical", lambda *_a, **_k: [], raising=True)
    monkeypatch.setattr(recall_mod.EventRepository, "search_similar_by_content", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("should not call milvus when embedding fails")), raising=True)
    monkeypatch.setattr(recall_mod.EventRepository, "filter_entity_ids_in_dataset", lambda *_a, **_k: {entity_id}, raising=True)
    monkeypatch.setattr(recall_mod.EventRepository, "search_events_by_entities", lambda *_a, **_k: [event_id], raising=True)

    class _Ev:
        def __init__(self) -> None:
            self.id = event_id
            self.title = "QUIC transport"
            self.summary = "QUIC over UDP"
            self.content = "QUIC over UDP"
            self.content_vector = None

    class _Link:
        def __init__(self) -> None:
            self.entity_id = entity_id

    monkeypatch.setattr(recall_mod.EventRepository, "get_events_by_ids", lambda *_a, **_k: [_Ev()], raising=True)
    monkeypatch.setattr(recall_mod.EventRepository, "get_event_entities", lambda *_a, **_k: {str(event_id): [_Link()]}, raising=True)

    async def _boom(_text: str) -> list[float]:
        await yield_control()
        raise RuntimeError("embedding provider down")

    searcher = RecallSearcher()
    monkeypatch.setattr(searcher.processor, "generate_embedding", _boom, raising=True)

    cfg = SearchConfig(query="QUIC transport", tenant_id=tenant_id, dataset_id=dataset_id, account_id="demo")
    out = await searcher.search(cfg)

    assert out.query_vector == []
    assert out.key_final and out.key_final[0]["method"] == "lexical_match"
    assert str(event_id) in list(out.event_ids or [])


@pytest.mark.asyncio
async def test_kg_recall_uses_lexical_events_when_embeddings_and_entity_recall_miss(monkeypatch: pytest.MonkeyPatch) -> None:
    """Event title/summary fallback covers early KG graphs with sparse entity aliases."""
    from app.core import config as config_mod

    monkeypatch.setattr(config_mod.settings, "KG_ENABLED", True, raising=False)
    monkeypatch.setattr(config_mod.settings, "KG_SEARCH_VECTOR_RECALL_ENABLED", True, raising=False)

    from app.rag.kg.search.config import SearchConfig
    from app.rag.kg.search.recall import RecallSearcher

    tenant_id = UUID(int=1)
    dataset_id = UUID(int=8)
    event_id = UUID(int=456)

    import app.rag.kg.search.recall as recall_mod

    monkeypatch.setattr(recall_mod, "get_session", lambda: type("_S", (), {"close": lambda _self: None})(), raising=True)
    monkeypatch.setattr(recall_mod.AliasRepository, "match_aliases", lambda *_a, **_k: [], raising=True)
    monkeypatch.setattr(recall_mod.EntityRepository, "search_similar", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("should not call milvus when embedding fails")), raising=True)
    monkeypatch.setattr(recall_mod.EntityRepository, "search_lexical", lambda *_a, **_k: [], raising=True)
    monkeypatch.setattr(recall_mod.EventRepository, "search_similar_by_content", lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("should not call milvus when embedding fails")), raising=True)
    monkeypatch.setattr(recall_mod.EventRepository, "search_events_by_entities", lambda *_a, **_k: [], raising=True)
    monkeypatch.setattr(
        recall_mod.EventRepository,
        "search_events_lexical",
        lambda *_a, **_k: [
            {
                "event_id": str(event_id),
                "title": "FastAPI operations",
                "summary": "FastAPI validation and documentation",
                "similarity": 0.9,
                "method": "lexical_match",
            }
        ],
        raising=True,
    )

    class _Ev:
        def __init__(self) -> None:
            self.id = event_id
            self.title = "FastAPI operations"
            self.summary = "FastAPI validation and documentation"
            self.content = "FastAPI validation and documentation"
            self.content_vector = None

    monkeypatch.setattr(recall_mod.EventRepository, "get_events_by_ids", lambda *_a, **_k: [_Ev()], raising=True)
    monkeypatch.setattr(recall_mod.EventRepository, "get_event_entities", lambda *_a, **_k: {}, raising=True)

    async def _boom(_text: str) -> list[float]:
        await yield_control()
        raise RuntimeError("embedding provider down")

    searcher = RecallSearcher()
    monkeypatch.setattr(searcher.processor, "generate_embedding", _boom, raising=True)

    cfg = SearchConfig(query="FastAPI validation", tenant_id=tenant_id, dataset_id=dataset_id, account_id="demo")
    out = await searcher.search(cfg)

    assert out.query_vector == []
    assert str(event_id) in list(out.event_ids or [])
