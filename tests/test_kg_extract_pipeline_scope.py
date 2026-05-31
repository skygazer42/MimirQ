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
    def __init__(self, chunk_id: UUID, chunk_index: int, *, doc_metadata=None):
        self.id = chunk_id
        self.chunk_index = chunk_index
        self.doc_metadata = doc_metadata or {}


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

    def commit(self):  # noqa: D401
        """No-op."""

    def refresh(self, _obj):  # noqa: ANN001
        return


@pytest.mark.asyncio
async def test_kg_extract_scopes_chunks_to_active_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    When a document has multiple chunk versions (pipeline_hash A/B), KG extraction should
    default to the active_pipeline_hash so it doesn't mix versions.
    """
    from app.core import config as config_mod
    from app.rag.kg.api.routes import KGExtractionOptions, run_kg_extraction_for_document

    monkeypatch.setattr(config_mod.settings, "KG_ENABLED", True, raising=False)

    called: dict[str, object] = {}

    async def _fake_extract_events(chunk_ids, tenant_id=None, *, chunks=None, **_k):  # noqa: ANN001
        await yield_control()
        called["chunk_ids"] = [str(cid) for cid in chunk_ids]
        called["chunks"] = chunks
        return [{"id": "e1"}]

    import app.rag.kg.api.routes as routes_mod

    monkeypatch.setattr(routes_mod, "extract_events", _fake_extract_events, raising=True)

    active_hash = "ph-active"
    other_hash = "ph-other"
    doc = _FakeDoc(doc_metadata={"active_pipeline_hash": active_hash, "pipeline_hash": other_hash})
    chunks = [
        _FakeChunk(UUID(int=1), 0, doc_metadata={"pipeline_hash": active_hash}),
        _FakeChunk(UUID(int=2), 1, doc_metadata={"pipeline_hash": other_hash}),
        _FakeChunk(UUID(int=3), 2, doc_metadata={"pipeline_hash": active_hash}),
    ]
    db = _FakeSession(doc, chunks)

    resp = Response()
    out = await run_kg_extraction_for_document(
        document_id=UUID(int=99),
        response=resp,
        options=KGExtractionOptions(async_mode=False),
        tenant_id=UUID(int=123),
        account_id="u",
        db=db,
    )

    assert out.chunk_count == 2
    assert called.get("chunk_ids") == [str(UUID(int=1)), str(UUID(int=3))]


@pytest.mark.asyncio
async def test_kg_extract_async_job_id_uses_active_pipeline_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import config as config_mod
    from app.rag.kg.api.routes import KGExtractionOptions, run_kg_extraction_for_document

    monkeypatch.setattr(config_mod.settings, "KG_ENABLED", True, raising=False)
    monkeypatch.setattr(config_mod.settings, "TASK_QUEUE_ENABLED", True, raising=False)

    active_hash = "ph-active"
    current_hash = "ph-current"

    async def _fake_enqueue_kg_extraction(*, job_id=None, **_k):  # noqa: ANN001
        await yield_control()
        assert job_id is not None
        assert job_id.endswith(f":{active_hash}")
        assert current_hash not in str(job_id)
        return "task-1"

    import app.tasks.queue as queue_mod

    monkeypatch.setattr(queue_mod, "enqueue_kg_extraction", _fake_enqueue_kg_extraction, raising=True)

    doc = _FakeDoc(doc_metadata={"active_pipeline_hash": active_hash, "pipeline_hash": current_hash})
    db = _FakeSession(doc, [_FakeChunk(UUID(int=1), 0, doc_metadata={"pipeline_hash": active_hash})])

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
    assert out.chunk_count == 1


@pytest.mark.asyncio
async def test_kg_extract_can_override_pipeline_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import config as config_mod
    from app.rag.kg.api.routes import KGExtractionOptions, run_kg_extraction_for_document

    monkeypatch.setattr(config_mod.settings, "KG_ENABLED", True, raising=False)

    called: dict[str, object] = {}

    async def _fake_extract_events(chunk_ids, tenant_id=None, *, chunks=None, **_k):  # noqa: ANN001
        await yield_control()
        called["chunk_ids"] = [str(cid) for cid in chunk_ids]
        called["chunks"] = chunks
        return [{"id": "e1"}]

    import app.rag.kg.api.routes as routes_mod

    monkeypatch.setattr(routes_mod, "extract_events", _fake_extract_events, raising=True)

    active_hash = "ph-active"
    other_hash = "ph-other"
    doc = _FakeDoc(doc_metadata={"active_pipeline_hash": active_hash, "pipeline_hash": other_hash})
    chunks = [
        _FakeChunk(UUID(int=1), 0, doc_metadata={"pipeline_hash": active_hash}),
        _FakeChunk(UUID(int=2), 1, doc_metadata={"pipeline_hash": other_hash}),
        _FakeChunk(UUID(int=3), 2, doc_metadata={"pipeline_hash": active_hash}),
    ]
    db = _FakeSession(doc, chunks)

    resp = Response()
    out = await run_kg_extraction_for_document(
        document_id=UUID(int=99),
        response=resp,
        options=KGExtractionOptions(async_mode=False, pipeline_hash=other_hash),
        tenant_id=UUID(int=123),
        account_id="u",
        db=db,
    )

    assert out.chunk_count == 1
    assert called.get("chunk_ids") == [str(UUID(int=2))]


@pytest.mark.asyncio
async def test_kg_extract_async_can_override_pipeline_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core import config as config_mod
    from app.rag.kg.api.routes import KGExtractionOptions, run_kg_extraction_for_document

    monkeypatch.setattr(config_mod.settings, "KG_ENABLED", True, raising=False)
    monkeypatch.setattr(config_mod.settings, "TASK_QUEUE_ENABLED", True, raising=False)

    active_hash = "ph-active"
    other_hash = "ph-other"

    async def _fake_enqueue_kg_extraction(*, job_id=None, pipeline_hash=None, **_k):  # noqa: ANN001
        await yield_control()
        assert pipeline_hash == other_hash
        assert job_id is not None and str(job_id).endswith(f":{other_hash}")
        return "task-1"

    import app.tasks.queue as queue_mod

    monkeypatch.setattr(queue_mod, "enqueue_kg_extraction", _fake_enqueue_kg_extraction, raising=True)

    doc = _FakeDoc(doc_metadata={"active_pipeline_hash": active_hash, "pipeline_hash": other_hash})
    db = _FakeSession(doc, [_FakeChunk(UUID(int=1), 0, doc_metadata={"pipeline_hash": other_hash})])

    resp = Response()
    out = await run_kg_extraction_for_document(
        document_id=UUID(int=2),
        options=KGExtractionOptions(async_mode=True, pipeline_hash=other_hash),
        tenant_id=UUID(int=3),
        account_id="u",
        response=resp,
        db=db,
    )
    assert resp.status_code == 202
    assert out.chunk_count == 1
