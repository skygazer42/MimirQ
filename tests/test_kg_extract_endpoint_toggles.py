from __future__ import annotations

from uuid import UUID

import pytest
from fastapi import Response

from tests.helpers.async_utils import yield_control


class _FakeDoc:
    def __init__(self, *, doc_metadata=None, dataset_id=None, status: str = "completed"):
        self.doc_metadata = doc_metadata or {}
        self.dataset_id = dataset_id
        self.status = status


class _FakeChunk:
    def __init__(self, chunk_id: UUID, chunk_index: int):
        self.id = chunk_id
        self.chunk_index = chunk_index


class _FakeQuery:
    def __init__(self, kind: str, doc: _FakeDoc | None, chunks: list[_FakeChunk]):
        self._kind = kind
        self._doc = doc
        self._chunks = chunks

    def filter(self, *args, **kwargs):  # noqa: ANN001
        return self

    def first(self):  # noqa: ANN201
        if self._kind == "doc":
            return self._doc
        return None

    def order_by(self, *args, **kwargs):  # noqa: ANN001
        return self

    def all(self):  # noqa: ANN201
        if self._kind == "chunks":
            return self._chunks
        return []


class _FakeSession:
    def __init__(self, doc: _FakeDoc | None, chunks: list[_FakeChunk]):
        self._doc = doc
        self._chunks = chunks

    def query(self, model):  # noqa: ANN001
        name = getattr(model, "__name__", "")
        if name == "Document":
            return _FakeQuery("doc", self._doc, self._chunks)
        if name == "DocumentChunk":
            return _FakeQuery("chunks", self._doc, self._chunks)
        return _FakeQuery("other", self._doc, self._chunks)


@pytest.mark.asyncio
async def test_kg_extract_endpoint_passes_extract_toggles(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.rag.kg.api.routes as routes_mod
    from app.core import config as config_mod
    from app.rag.kg.api.routes import KGExtractionOptions, run_kg_extraction_for_document

    monkeypatch.setattr(config_mod.settings, "KG_ENABLED", True, raising=False)

    called: dict[str, object] = {}

    async def _fake_extract_events(chunk_ids, tenant_id=None, **kwargs):  # noqa: ANN001, ANN002, ANN003
        await yield_control()
        called["chunk_ids"] = list(chunk_ids or [])
        called["tenant_id"] = tenant_id
        called.update(kwargs)
        return [object(), object()]

    monkeypatch.setattr(routes_mod, "extract_events", _fake_extract_events, raising=True)

    doc = _FakeDoc(doc_metadata={"pipeline_hash": "ph"})
    db = _FakeSession(doc, [_FakeChunk(UUID(int=1), 0), _FakeChunk(UUID(int=2), 1)])

    resp = Response()
    out = await run_kg_extraction_for_document(
        document_id=UUID(int=2),
        response=resp,
        options=KGExtractionOptions(
            async_mode=False,
            replace_existing=True,
            prune_orphan_entities=True,
            extract_relations=False,
            extract_skills=True,
        ),
        tenant_id=UUID(int=3),
        account_id="u",
        db=db,
    )

    assert out.chunk_count == 2
    assert out.event_count == 2
    assert called.get("extract_relations") is False
    assert called.get("extract_skills") is True
