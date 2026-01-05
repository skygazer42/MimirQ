from __future__ import annotations

import pytest
from fastapi import HTTPException, Response
from uuid import UUID


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
    from app.rag.kg.api.routes import run_kg_extraction_for_document
    from app.services.dataset_service import DatasetService

    monkeypatch.setattr(config_mod.settings, "KG_ENABLED", True, raising=False)
    monkeypatch.setattr(config_mod.settings, "TASK_QUEUE_ENABLED", False, raising=False)
    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)

    doc = _FakeDoc(doc_metadata={"pipeline_hash": "ph"})
    db = _FakeSession(doc, [_FakeChunk(UUID(int=1), 0)])

    with pytest.raises(HTTPException) as exc:
        await run_kg_extraction_for_document(
            document_id=UUID(int=2),
            async_mode=True,
            prompt_template_id=None,
            prompt_template_key=None,
            prompt_ab_experiment_key=None,
            tenant_id=UUID(int=3),
            account_id="u",
            response=Response(),
            db=db,
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_kg_extract_async_enqueues_and_returns_202(monkeypatch):
    from app.core import config as config_mod
    from app.rag.kg.api.routes import run_kg_extraction_for_document
    from app.services.dataset_service import DatasetService

    monkeypatch.setattr(config_mod.settings, "KG_ENABLED", True, raising=False)
    monkeypatch.setattr(config_mod.settings, "TASK_QUEUE_ENABLED", True, raising=False)
    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)

    async def _fake_enqueue_kg_extraction(*, tenant_id, document_id, requested_by, job_id=None):  # noqa: ANN001
        assert requested_by == "u"
        assert job_id and job_id.startswith("kg:")
        return "task-1"

    import app.tasks.queue as queue_mod

    monkeypatch.setattr(queue_mod, "enqueue_kg_extraction", _fake_enqueue_kg_extraction, raising=True)

    doc = _FakeDoc(doc_metadata={"pipeline_hash": "ph"})
    db = _FakeSession(doc, [_FakeChunk(UUID(int=1), 0), _FakeChunk(UUID(int=2), 1)])

    resp = Response()
    out = await run_kg_extraction_for_document(
        document_id=UUID(int=2),
        async_mode=True,
        prompt_template_id=None,
        prompt_template_key=None,
        prompt_ab_experiment_key=None,
        tenant_id=UUID(int=3),
        account_id="u",
        response=resp,
        db=db,
    )
    assert resp.status_code == 202
    assert resp.headers.get("X-Task-Id") == "task-1"
    assert out.event_count == 0
    assert out.chunk_count == 2


@pytest.mark.asyncio
async def test_kg_extract_async_queue_returns_none_raises_503(monkeypatch):
    from app.core import config as config_mod
    from app.rag.kg.api.routes import run_kg_extraction_for_document
    from app.services.dataset_service import DatasetService

    monkeypatch.setattr(config_mod.settings, "KG_ENABLED", True, raising=False)
    monkeypatch.setattr(config_mod.settings, "TASK_QUEUE_ENABLED", True, raising=False)
    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)

    async def _fake_enqueue_kg_extraction(*, tenant_id, document_id, requested_by, job_id=None):  # noqa: ANN001
        return None

    import app.tasks.queue as queue_mod

    monkeypatch.setattr(queue_mod, "enqueue_kg_extraction", _fake_enqueue_kg_extraction, raising=True)

    doc = _FakeDoc(doc_metadata={"pipeline_hash": "ph"})
    db = _FakeSession(doc, [_FakeChunk(UUID(int=1), 0)])

    with pytest.raises(HTTPException) as exc:
        await run_kg_extraction_for_document(
            document_id=UUID(int=2),
            async_mode=True,
            prompt_template_id=None,
            prompt_template_key=None,
            prompt_ab_experiment_key=None,
            tenant_id=UUID(int=3),
            account_id="u",
            response=Response(),
            db=db,
        )
    assert exc.value.status_code == 503
