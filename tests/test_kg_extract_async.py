from __future__ import annotations

from uuid import UUID

import pytest
from fastapi import HTTPException, Response

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
        # Match imports in route module
        name = getattr(model, "__name__", "")
        if name == "Document":
            return _FakeQuery("doc", self._doc, self._chunks)
        if name == "DocumentChunk":
            return _FakeQuery("chunks", self._doc, self._chunks)
        return _FakeQuery("other", self._doc, self._chunks)

    def commit(self):  # noqa: D401
        """No-op."""

    def refresh(self, _obj):  # noqa: ANN001
        return


@pytest.mark.asyncio
async def test_kg_extract_async_requires_queue_enabled(monkeypatch):
    from app.core import config as config_mod
    from app.rag.kg.api.routes import KGExtractionOptions, run_kg_extraction_for_document

    monkeypatch.setattr(config_mod.settings, "KG_ENABLED", True, raising=False)
    monkeypatch.setattr(config_mod.settings, "TASK_QUEUE_ENABLED", False, raising=False)

    doc = _FakeDoc(doc_metadata={"pipeline_hash": "ph"})
    db = _FakeSession(doc, [_FakeChunk(UUID(int=1), 0)])

    with pytest.raises(HTTPException) as exc:
        await run_kg_extraction_for_document(
            document_id=UUID(int=2),
            options=KGExtractionOptions(async_mode=True),
            tenant_id=UUID(int=3),
            account_id="u",
            response=Response(),
            db=db,
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_kg_extract_async_enqueues_and_returns_202(monkeypatch):
    from app.core import config as config_mod
    from app.rag.kg.api.routes import KGExtractionOptions, run_kg_extraction_for_document

    monkeypatch.setattr(config_mod.settings, "KG_ENABLED", True, raising=False)
    monkeypatch.setattr(config_mod.settings, "TASK_QUEUE_ENABLED", True, raising=False)

    async def _fake_enqueue_kg_extraction(  # noqa: ANN001
        *,
        tenant_id,
        document_id,
        requested_by,
        job_id=None,
        pipeline_hash=None,
        replace_existing=None,
        prune_orphan_entities=None,
        extract_relations=None,
        extract_skills=None,
    ):
        await yield_control()
        assert requested_by == "u"
        assert job_id and job_id.startswith("kg:")
        assert pipeline_hash == "ph"
        assert replace_existing is True
        assert prune_orphan_entities is True
        assert extract_relations is None
        assert extract_skills is None
        return "task-1"

    import app.tasks.queue as queue_mod

    monkeypatch.setattr(queue_mod, "enqueue_kg_extraction", _fake_enqueue_kg_extraction, raising=True)

    doc = _FakeDoc(doc_metadata={"pipeline_hash": "ph"})
    db = _FakeSession(doc, [_FakeChunk(UUID(int=1), 0), _FakeChunk(UUID(int=2), 1)])

    resp = Response()
    out = await run_kg_extraction_for_document(
        document_id=UUID(int=2),
        options=KGExtractionOptions(async_mode=True),
        tenant_id=UUID(int=3),
        account_id="u",
        response=resp,
        db=db,
    )
    assert resp.status_code == 202
    assert resp.headers.get("X-Task-Id") == "task-1"
    assert out.event_count == 0
    assert out.chunk_count == 2
