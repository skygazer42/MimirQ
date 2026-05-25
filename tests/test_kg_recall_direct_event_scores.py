from __future__ import annotations

from uuid import UUID

import pytest


@pytest.mark.asyncio
async def test_recall_preserves_direct_event_similarity_for_local_factoid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.kg.search.recall as recall_mod
    from app.rag.kg.search.config import SearchConfig

    good_id = UUID(int=1)
    weak_id = UUID(int=2)

    class _FakeSession:
        def close(self) -> None:
            return

    class _FakeAliasRepo:
        def __init__(self, _session):  # noqa: ANN001
            return

        def match_aliases(self, **_kwargs):  # noqa: ANN003
            return []

    class _FakeEntityRepo:
        def __init__(self, _session):  # noqa: ANN001
            return

        def search_lexical(self, **_kwargs):  # noqa: ANN003
            return []

    class _Event:
        def __init__(self, event_id: UUID):
            self.id = event_id
            self.content_vector = []
            self.chunk_id = None
            self.document_id = None

    class _FakeEventRepo:
        def __init__(self, _session):  # noqa: ANN001
            return

        def search_events_lexical(self, **_kwargs):  # noqa: ANN003
            return [
                {"event_id": str(good_id), "similarity": 1.0, "method": "lexical_match"},
                {"event_id": str(weak_id), "similarity": 0.4, "method": "lexical_match"},
            ]

        def search_events_by_entities(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
            return []

        def get_events_by_ids(self, event_ids, **_kwargs):  # noqa: ANN001
            return [_Event(UUID(str(event_id))) for event_id in event_ids]

        def get_event_entities(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
            return {}

    monkeypatch.setattr(recall_mod, "get_session", lambda: _FakeSession(), raising=True)
    monkeypatch.setattr(recall_mod, "AliasRepository", _FakeAliasRepo, raising=True)
    monkeypatch.setattr(recall_mod, "EntityRepository", _FakeEntityRepo, raising=True)
    monkeypatch.setattr(recall_mod, "EventRepository", _FakeEventRepo, raising=True)

    cfg = SearchConfig(
        query="Which paper proposed layer normalization?",
        tenant_id=UUID(int=10),
        dataset_id=UUID(int=11),
        account_id="acct",
        query_mode="local",
        query_mode_reason_codes=["dataset_factoid_scope"],
        query_mode_confidence="medium",
    )

    out = await recall_mod.RecallSearcher().search(cfg)

    assert out.event_scores[str(good_id)] == pytest.approx(1.0)
    assert out.event_scores[str(weak_id)] == pytest.approx(0.4)
