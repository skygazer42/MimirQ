from __future__ import annotations

from uuid import UUID

import pytest


@pytest.mark.asyncio
async def test_kg_pagerank_rerank_emits_ranking_features(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.kg.search.ranking.pagerank as pagerank_mod
    from app.rag.kg.search.config import SearchConfig

    class _FakeSession:
        def close(self) -> None:
            return

    monkeypatch.setattr(pagerank_mod, "get_session", lambda: _FakeSession(), raising=True)

    class _Ent:
        def __init__(self, ent_id: UUID):
            self.id = ent_id

    class _Ev:
        def __init__(self, ev_id: UUID, *, chunk_id: UUID):
            self.id = ev_id
            self.title = ""
            self.summary = ""
            self.content = ""
            self.content_vector = []
            self.document_id = None
            self.chunk_id = chunk_id

    ent_a = _Ent(UUID(int=1))
    ent_b = _Ent(UUID(int=2))
    ev1 = _Ev(UUID(int=101), chunk_id=UUID(int=201))
    ev2 = _Ev(UUID(int=102), chunk_id=UUID(int=202))

    class _FakeEventRepository:
        def __init__(self, _session):  # noqa: ANN001
            return

        def get_events_by_ids(  # noqa: ANN202
            self,
            event_ids,
            *,
            tenant_id=None,
            document_ids=None,
            dataset_id=None,
            account_id=None,
        ):
            want = {str(x) for x in (event_ids or [])}
            return [e for e in (ev1, ev2) if str(e.id) in want]

        def get_entities_for_events(self, event_ids, *, tenant_id=None):  # noqa: ANN001
            return {
                str(ev1.id): [ent_a],
                str(ev2.id): [ent_a, ent_b],
            }

    monkeypatch.setattr(pagerank_mod, "EventRepository", _FakeEventRepository, raising=True)

    cfg = SearchConfig(query="q", tenant_id=UUID(int=9))
    key_final = [
        {"entity_id": str(ent_a.id), "weight": 1.0},
        {"entity_id": str(ent_b.id), "weight": 0.5},
    ]
    event_scores = {str(ev1.id): 0.9, str(ev2.id): 0.1}
    event_hops = {str(ev1.id): 2, str(ev2.id): 3}

    out = await pagerank_mod.RerankPageRankSearcher().rerank(
        cfg,
        [str(ev1.id), str(ev2.id)],
        key_final,
        event_scores,
        query_vector=[0.0],
        event_hops=event_hops,
    )

    events = out.get("events") or []
    assert {str(e.get("id")) for e in events} == {str(ev1.id), str(ev2.id)}
    by_id = {str(e.get("id")): e for e in events}

    assert by_id[str(ev1.id)].get("kg_path_length") == 2
    assert by_id[str(ev2.id)].get("kg_path_length") == 3
    assert by_id[str(ev1.id)].get("kg_shared_events") == 1
    assert by_id[str(ev2.id)].get("kg_shared_events") == 2

