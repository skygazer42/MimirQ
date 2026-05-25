from __future__ import annotations

from uuid import UUID

import pytest


@pytest.mark.asyncio
async def test_rrf_preserves_recall_order_when_scores_tie(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.kg.search.ranking.rrf as rrf_mod
    from app.rag.kg.search.config import SearchConfig

    first_id = UUID(int=2)
    second_id = UUID(int=1)

    class _FakeSession:
        def close(self) -> None:
            return

    class _Event:
        def __init__(self, ev_id: UUID):
            self.id = ev_id
            self.title = "same"
            self.summary = "same"
            self.content = "same"
            self.content_vector = []
            self.document_id = None
            self.chunk_id = None

    class _FakeEventRepo:
        def __init__(self, _session):  # noqa: ANN001
            return

        def get_events_by_ids(self, event_ids, **_kwargs):  # noqa: ANN001
            return [_Event(UUID(str(event_id))) for event_id in event_ids]

    monkeypatch.setattr(rrf_mod, "get_session", lambda: _FakeSession(), raising=True)
    monkeypatch.setattr(rrf_mod, "EventRepository", _FakeEventRepo, raising=True)

    out = await rrf_mod.RerankRRFSearcher().rerank(
        SearchConfig(query="unmatched query"),
        [str(first_id), str(second_id)],
        {str(first_id): 1.0, str(second_id): 1.0},
        query_vector=[],
    )

    assert [item["id"] for item in out["events"]][:2] == [str(first_id), str(second_id)]


@pytest.mark.asyncio
async def test_rrf_boosts_matching_source_document_label(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.kg.search.ranking.rrf as rrf_mod
    from app.rag.kg.search.config import SearchConfig

    citation_event_id = UUID(int=1)
    target_event_id = UUID(int=2)
    citation_doc_id = UUID(int=101)
    target_doc_id = UUID(int=102)

    class _FakeSession:
        def close(self) -> None:
            return

    class _Event:
        def __init__(self, ev_id: UUID, doc_id: UUID, title: str):
            self.id = ev_id
            self.title = title
            self.summary = title
            self.content = title
            self.content_vector = []
            self.document_id = doc_id
            self.chunk_id = None

    class _FakeEventRepo:
        def __init__(self, _session):  # noqa: ANN001
            return

        def get_events_by_ids(self, event_ids, **_kwargs):  # noqa: ANN001
            events = {
                str(citation_event_id): _Event(
                    citation_event_id,
                    citation_doc_id,
                    "Neural machine translation by jointly learning to align and translate.",
                ),
                str(target_event_id): _Event(
                    target_event_id,
                    target_doc_id,
                    "2 BACKGROUND: NEURAL MACHINE TRANSLATION",
                ),
            }
            return [events[str(event_id)] for event_id in event_ids]

    monkeypatch.setattr(rrf_mod, "get_session", lambda: _FakeSession(), raising=True)
    monkeypatch.setattr(rrf_mod, "EventRepository", _FakeEventRepo, raising=True)
    monkeypatch.setattr(
        rrf_mod.RerankRRFSearcher,
        "_load_document_labels",
        lambda _self, _session, _events: {
            str(citation_doc_id): "graph-neural-networks-review_1812.08434.pdf",
            str(target_doc_id): "neural-machine-translation-align-translate_1409.0473.pdf",
        },
        raising=False,
    )

    out = await rrf_mod.RerankRRFSearcher().rerank(
        SearchConfig(query="Which neural machine translation paper jointly learns to align and translate?"),
        [str(citation_event_id), str(target_event_id)],
        {str(citation_event_id): 1.0, str(target_event_id): 1.0},
        query_vector=[],
    )

    assert [item["id"] for item in out["events"]][:2] == [str(target_event_id), str(citation_event_id)]
