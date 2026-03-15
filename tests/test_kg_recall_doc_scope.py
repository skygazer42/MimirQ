from __future__ import annotations

import asyncio
from uuid import UUID

import pytest


@pytest.mark.asyncio
async def test_kg_recall_filters_entities_by_document_scope(monkeypatch: pytest.MonkeyPatch):
    import app.rag.kg.search.recall as recall_mod
    from app.rag.kg.search.config import SearchConfig
    from app.rag.kg.search.recall import RecallSearcher

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
            return [
                {"entity_id": str(UUID(int=10)), "name": "A", "type": "t", "similarity": 0.9},
                {"entity_id": str(UUID(int=11)), "name": "B", "type": "t", "similarity": 0.8},
            ]

    class _FakeEventRepository:
        def __init__(self, _session):  # noqa: ANN001
            return

        def filter_entity_ids_in_documents(self, entity_ids, *, tenant_id, document_ids):  # noqa: ANN001
            assert entity_ids
            assert tenant_id
            assert document_ids
            return {UUID(int=10)}

        def search_events_by_entities(self, *_a, **_k):  # noqa: ANN001
            return []

        def search_similar_by_content(self, *_a, **_k):  # noqa: ANN001
            return []

        def get_events_by_ids(self, *_a, **_k):  # noqa: ANN001
            return []

        def get_event_entities(self, *_a, **_k):  # noqa: ANN001
            return {}

    monkeypatch.setattr(recall_mod, "EntityRepository", _FakeEntityRepository, raising=True)
    monkeypatch.setattr(recall_mod, "EventRepository", _FakeEventRepository, raising=True)

    config = SearchConfig(query="q", tenant_id=UUID(int=1), document_ids=[UUID(int=2)])
    result = await RecallSearcher().search(config)
    assert [e["entity_id"] for e in result.key_final] == [str(UUID(int=10))]


@pytest.mark.asyncio
async def test_kg_recall_filters_entities_by_dataset_scope(monkeypatch: pytest.MonkeyPatch):
    import app.rag.kg.search.recall as recall_mod
    from app.rag.kg.search.config import SearchConfig
    from app.rag.kg.search.recall import RecallSearcher

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
            return [
                {"entity_id": str(UUID(int=10)), "name": "A", "type": "t", "similarity": 0.9},
                {"entity_id": str(UUID(int=11)), "name": "B", "type": "t", "similarity": 0.8},
            ]

    class _FakeEventRepository:
        def __init__(self, _session):  # noqa: ANN001
            return

        def filter_entity_ids_in_dataset(self, entity_ids, *, tenant_id, dataset_id, account_id):  # noqa: ANN001
            assert entity_ids
            assert tenant_id
            assert dataset_id == UUID(int=3)
            assert account_id == "u"
            return {UUID(int=10)}

        def search_events_by_entities(self, *_a, **_k):  # noqa: ANN001
            return []

        def search_similar_by_content(self, *_a, **_k):  # noqa: ANN001
            return []

        def get_events_by_ids(self, *_a, **_k):  # noqa: ANN001
            return []

        def get_event_entities(self, *_a, **_k):  # noqa: ANN001
            return {}

    monkeypatch.setattr(recall_mod, "EntityRepository", _FakeEntityRepository, raising=True)
    monkeypatch.setattr(recall_mod, "EventRepository", _FakeEventRepository, raising=True)

    config = SearchConfig(query="q", tenant_id=UUID(int=1), dataset_id=UUID(int=3), account_id="u")
    result = await RecallSearcher().search(config)
    assert [e["entity_id"] for e in result.key_final] == [str(UUID(int=10))]
