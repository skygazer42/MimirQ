from __future__ import annotations

from uuid import UUID

import pytest


@pytest.mark.asyncio
async def test_pagerank_rerank_prefers_exact_query_phrase_when_graph_scores_tie(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.kg.search.ranking.pagerank as pagerank_mod
    from app.rag.kg.search.config import SearchConfig

    generic_id = UUID(int=1)
    exact_id = UUID(int=2)

    class _FakeSession:
        def close(self) -> None:
            return

    class _Event:
        def __init__(self, ev_id: UUID, title: str, content: str):
            self.id = ev_id
            self.title = title
            self.summary = content
            self.content = content
            self.content_vector = []
            self.document_id = None
            self.chunk_id = None

    class _FakeEventRepo:
        def __init__(self, _session):  # noqa: ANN001
            return

        def get_events_by_ids(self, event_ids, **_kwargs):  # noqa: ANN001
            by_id = {
                str(generic_id): _Event(
                    generic_id,
                    "Neural networks for machine translation",
                    "A generic neural network model uses attention over hidden states.",
                ),
                str(exact_id): _Event(
                    exact_id,
                    "Graph neural networks: A review of methods and applications",
                    "Graph neural networks including graph convolution and graph attention networks.",
                ),
            }
            return [by_id[str(event_id)] for event_id in event_ids]

        def get_entities_for_events(self, _event_ids, **_kwargs):  # noqa: ANN001
            return {}

    monkeypatch.setattr(pagerank_mod, "get_session", lambda: _FakeSession(), raising=True)
    monkeypatch.setattr(pagerank_mod, "EventRepository", _FakeEventRepo, raising=True)

    out = await pagerank_mod.RerankPageRankSearcher().rerank(
        SearchConfig(
            query="Which survey reviews graph neural networks including graph convolution and graph attention networks?"
        ),
        [str(generic_id), str(exact_id)],
        key_final=[],
        event_scores={str(generic_id): 0.0, str(exact_id): 0.0},
        query_vector=[],
    )

    assert [item["id"] for item in out["events"]][:2] == [str(exact_id), str(generic_id)]
    assert out["events"][0]["score"] > out["events"][1]["score"]

