from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

import pytest

from tests.helpers.async_utils import yield_control


def test_kg_serving_layer_caps_dense_events_per_chunk_and_document() -> None:
    from app.rag.kg.search.recall import apply_serving_layer_budget

    doc_a = UUID(int=1)
    doc_b = UUID(int=2)
    events = [
        SimpleNamespace(id=UUID(int=10), document_id=doc_a, chunk_id=UUID(int=100)),
        SimpleNamespace(id=UUID(int=11), document_id=doc_a, chunk_id=UUID(int=100)),
        SimpleNamespace(id=UUID(int=12), document_id=doc_a, chunk_id=UUID(int=100)),
        SimpleNamespace(id=UUID(int=13), document_id=doc_a, chunk_id=UUID(int=101)),
        SimpleNamespace(id=UUID(int=14), document_id=doc_a, chunk_id=UUID(int=102)),
        SimpleNamespace(id=UUID(int=20), document_id=doc_b, chunk_id=UUID(int=200)),
    ]
    scores = {
        str(UUID(int=10)): 0.99,
        str(UUID(int=11)): 0.80,
        str(UUID(int=12)): 0.79,
        str(UUID(int=13)): 0.70,
        str(UUID(int=14)): 0.60,
        str(UUID(int=20)): 0.50,
    }

    budgeted = apply_serving_layer_budget(
        events,
        scores,
        enabled=True,
        max_events_per_chunk=2,
        max_events_per_document=3,
        min_score=0.0,
        bypass=False,
    )

    assert budgeted.event_ids == [
        str(UUID(int=10)),
        str(UUID(int=11)),
        str(UUID(int=13)),
        str(UUID(int=20)),
    ]
    assert budgeted.kept == 4
    assert budgeted.dropped == 2
    assert budgeted.dropped_by_chunk == 1
    assert budgeted.dropped_by_document == 1


def test_kg_serving_layer_can_bypass_for_explicit_global_analysis() -> None:
    from app.rag.kg.search.recall import apply_serving_layer_budget

    events = [
        SimpleNamespace(id=UUID(int=idx), document_id=UUID(int=1), chunk_id=UUID(int=100))
        for idx in range(1, 5)
    ]
    scores = {str(UUID(int=idx)): 1.0 / idx for idx in range(1, 5)}

    budgeted = apply_serving_layer_budget(
        events,
        scores,
        enabled=True,
        max_events_per_chunk=1,
        max_events_per_document=1,
        min_score=0.0,
        bypass=True,
    )

    assert budgeted.event_ids == [str(UUID(int=idx)) for idx in range(1, 5)]
    assert budgeted.dropped == 0
    assert budgeted.reason == "bypassed"


@pytest.mark.asyncio
async def test_kg_recall_applies_serving_layer_before_expand_and_rerank(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.kg.search.recall as recall_mod
    from app.core.config import settings
    from app.rag.kg.search.config import RecallConfig, SearchConfig
    from app.rag.kg.search.recall import RecallSearcher

    tenant_id = UUID(int=1)
    entity_id = UUID(int=50)
    doc_a = UUID(int=1)
    doc_b = UUID(int=2)
    event_ids = [UUID(int=value) for value in [10, 11, 12, 13, 14, 20]]
    events = [
        SimpleNamespace(id=event_ids[0], document_id=doc_a, chunk_id=UUID(int=100), content_vector=None),
        SimpleNamespace(id=event_ids[1], document_id=doc_a, chunk_id=UUID(int=100), content_vector=None),
        SimpleNamespace(id=event_ids[2], document_id=doc_a, chunk_id=UUID(int=100), content_vector=None),
        SimpleNamespace(id=event_ids[3], document_id=doc_a, chunk_id=UUID(int=101), content_vector=None),
        SimpleNamespace(id=event_ids[4], document_id=doc_a, chunk_id=UUID(int=102), content_vector=None),
        SimpleNamespace(id=event_ids[5], document_id=doc_b, chunk_id=UUID(int=200), content_vector=None),
    ]

    monkeypatch.setattr(settings, "KG_SEARCH_SERVING_LAYER_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "KG_SEARCH_SERVING_MAX_EVENTS_PER_CHUNK", 2, raising=False)
    monkeypatch.setattr(settings, "KG_SEARCH_SERVING_MAX_EVENTS_PER_DOCUMENT", 3, raising=False)
    monkeypatch.setattr(settings, "KG_SEARCH_SERVING_MIN_SCORE", 0.0, raising=False)
    monkeypatch.setattr(settings, "KG_SEARCH_SERVING_CANDIDATE_MULTIPLIER", 3, raising=False)
    monkeypatch.setattr(settings, "KG_SEARCH_MAX_RERANK_CANDIDATES", 0, raising=False)

    class _FakeSession:
        def close(self) -> None:
            return

    class _FakeEntityRepository:
        def __init__(self, _session):  # noqa: ANN001
            return

        def search_similar(self, *, query_vector, tenant_id, k, entity_type=None):  # noqa: ANN001
            return [{"entity_id": str(entity_id), "name": "QUIC", "type": "concept", "similarity": 1.0}]

    class _FakeAliasRepository:
        def __init__(self, _session):  # noqa: ANN001
            return

        def match_aliases(self, *_a, **_k):  # noqa: ANN001
            return []

    class _FakeEventRepository:
        def __init__(self, _session):  # noqa: ANN001
            return

        def search_events_by_entities(self, *_a, **_k):  # noqa: ANN001
            return list(event_ids)

        def search_similar_by_content(self, *_a, **_k):  # noqa: ANN001
            return []

        def get_events_by_ids(self, requested_ids, *_a, **_k):  # noqa: ANN001
            requested = {str(item) for item in requested_ids}
            return [event for event in events if str(event.id) in requested]

        def get_event_entities(self, requested_ids, *_a, **_k):  # noqa: ANN001
            return {
                str(event_id): [SimpleNamespace(entity_id=entity_id)]
                for event_id in requested_ids
            }

    monkeypatch.setattr(recall_mod, "get_session", lambda: _FakeSession(), raising=True)
    monkeypatch.setattr(recall_mod, "EntityRepository", _FakeEntityRepository, raising=True)
    monkeypatch.setattr(recall_mod, "AliasRepository", _FakeAliasRepository, raising=True)
    monkeypatch.setattr(recall_mod, "EventRepository", _FakeEventRepository, raising=True)

    async def _fake_generate_embedding(_text: str) -> list[float]:
        await yield_control()
        return [1.0]

    searcher = RecallSearcher()
    monkeypatch.setattr(searcher.processor, "generate_embedding", _fake_generate_embedding, raising=True)

    out = await searcher.search(
        SearchConfig(
            query="QUIC handshake",
            tenant_id=tenant_id,
            recall=RecallConfig(max_events=6),
        )
    )

    assert out.event_ids == [str(event_ids[0]), str(event_ids[1]), str(event_ids[3]), str(event_ids[5])]
    assert out.serving_layer["dropped_by_chunk"] == 1
    assert out.serving_layer["dropped_by_document"] == 1
    assert out.serving_layer["returned"] == 4
