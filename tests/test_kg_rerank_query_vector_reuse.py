from __future__ import annotations

from uuid import UUID

import pytest

from tests.helpers.async_utils import yield_control


@pytest.mark.asyncio
async def test_rrf_uses_provided_query_vector(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.kg.search.ranking.rrf as rrf_mod
    from app.rag.kg.search.config import SearchConfig

    class _FakeSession:
        def close(self) -> None:
            return

    monkeypatch.setattr(rrf_mod, "get_session", lambda: _FakeSession(), raising=True)

    async def _boom(self, _text: str):  # noqa: ANN001
        await yield_control()
        raise AssertionError("generate_embedding should not be called when query_vector is provided")

    monkeypatch.setattr(rrf_mod.DocumentProcessor, "generate_embedding", _boom, raising=True)

    class _Ev:
        def __init__(self, ev_id: UUID):
            self.id = ev_id
            self.title = "t"
            self.summary = "s"
            self.content = "c"
            self.content_vector = [0.0]
            self.document_id = None
            self.chunk_id = None

    class _FakeEventRepo:
        def __init__(self, _session):  # noqa: ANN001
            return

        def get_events_by_ids(self, _ids, *, tenant_id=None, document_ids=None, **_k):  # noqa: ANN001
            return [_Ev(UUID(int=1))]

    monkeypatch.setattr(rrf_mod, "EventRepository", _FakeEventRepo, raising=True)

    cfg = SearchConfig(query="q", tenant_id=UUID(int=2), document_ids=[UUID(int=3)])
    out = await rrf_mod.RerankRRFSearcher().rerank(
        cfg,
        [str(UUID(int=1))],
        {str(UUID(int=1)): 1.0},
        query_vector=[0.0],
    )
    assert out["events"]
