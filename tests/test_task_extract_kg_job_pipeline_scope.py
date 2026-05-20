from __future__ import annotations

from uuid import UUID

import pytest

from tests.helpers.async_utils import yield_control


class _FakeDoc:
    def __init__(self, *, doc_metadata=None, dataset_id=None, status: str = "completed"):
        self.id = UUID(int=2)
        self.tenant_id = UUID(int=3)
        self.doc_metadata = doc_metadata or {}
        self.dataset_id = dataset_id
        self.status = status


class _FakeChunk:
    def __init__(self, chunk_id: UUID, chunk_index: int, *, doc_metadata=None):
        self.id = chunk_id
        self.chunk_index = chunk_index
        self.doc_metadata = doc_metadata or {}
        self.document_id = UUID(int=2)
        self.tenant_id = UUID(int=3)


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

    def close(self) -> None:
        return


@pytest.mark.asyncio
async def test_extract_kg_job_scopes_chunks_to_active_pipeline(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Worker-side KG extraction must not mix chunk versions; it should default to
    document.active_pipeline_hash (fallback: document.pipeline_hash).
    """
    import app.tasks.jobs as jobs_mod

    called: dict[str, object] = {}

    async def _fake_extract_events(chunk_ids, tenant_id=None, *, chunks=None, **_k):  # noqa: ANN001
        await yield_control()
        called["chunk_ids"] = [str(cid) for cid in chunk_ids]
        called["chunks"] = chunks
        return [{"id": "e1"}]

    monkeypatch.setattr(jobs_mod, "SessionLocal", lambda: db, raising=True)

    import app.rag.kg.pipeline as kg_pipe_mod

    monkeypatch.setattr(kg_pipe_mod, "extract_events", _fake_extract_events, raising=True)

    active_hash = "ph-active"
    other_hash = "ph-other"
    doc = _FakeDoc(doc_metadata={"active_pipeline_hash": active_hash, "pipeline_hash": other_hash})
    chunks = [
        _FakeChunk(UUID(int=10), 0, doc_metadata={"pipeline_hash": active_hash}),
        _FakeChunk(UUID(int=11), 1, doc_metadata={"pipeline_hash": other_hash}),
        _FakeChunk(UUID(int=12), 2, doc_metadata={"pipeline_hash": active_hash}),
    ]
    db = _FakeSession(doc, chunks)

    out = await jobs_mod.extract_kg_job(
        ctx={},
        tenant_id=str(UUID(int=3)),
        document_id=str(UUID(int=2)),
        requested_by="u",
        replace_existing=None,
        prune_orphan_entities=None,
        extract_relations=None,
        extract_skills=None,
    )
    assert out.get("ok") is True
    assert out.get("event_count") == 1
    assert called.get("chunk_ids") == [str(UUID(int=10)), str(UUID(int=12))]


@pytest.mark.asyncio
async def test_extract_kg_job_can_override_pipeline_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.tasks.jobs as jobs_mod

    called: dict[str, object] = {}

    async def _fake_extract_events(chunk_ids, tenant_id=None, *, chunks=None, **_k):  # noqa: ANN001
        await yield_control()
        called["chunk_ids"] = [str(cid) for cid in chunk_ids]
        called["chunks"] = chunks
        return [{"id": "e1"}]

    monkeypatch.setattr(jobs_mod, "SessionLocal", lambda: db, raising=True)

    import app.rag.kg.pipeline as kg_pipe_mod

    monkeypatch.setattr(kg_pipe_mod, "extract_events", _fake_extract_events, raising=True)

    active_hash = "ph-active"
    other_hash = "ph-other"
    doc = _FakeDoc(doc_metadata={"active_pipeline_hash": active_hash, "pipeline_hash": other_hash})
    chunks = [
        _FakeChunk(UUID(int=10), 0, doc_metadata={"pipeline_hash": active_hash}),
        _FakeChunk(UUID(int=11), 1, doc_metadata={"pipeline_hash": other_hash}),
        _FakeChunk(UUID(int=12), 2, doc_metadata={"pipeline_hash": active_hash}),
    ]
    db = _FakeSession(doc, chunks)

    out = await jobs_mod.extract_kg_job(
        ctx={},
        tenant_id=str(UUID(int=3)),
        document_id=str(UUID(int=2)),
        requested_by="u",
        replace_existing=None,
        prune_orphan_entities=None,
        extract_relations=None,
        extract_skills=None,
        pipeline_hash=other_hash,
    )
    assert out.get("ok") is True
    assert out.get("event_count") == 1
    assert called.get("chunk_ids") == [str(UUID(int=11))]


@pytest.mark.asyncio
async def test_extract_kg_job_uses_configured_concurrency_retry_defer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.tasks.jobs as jobs_mod

    tenant_calls: list[int] = []
    dataset_calls: list[int] = []

    async def _fake_tenant_acquire(_redis, **kwargs):  # noqa: ANN001
        await yield_control()
        tenant_calls.append(int(kwargs.get("retry_defer_sec") or 0))
        return None

    async def _fake_dataset_acquire(_redis, **kwargs):  # noqa: ANN001
        await yield_control()
        dataset_calls.append(int(kwargs.get("retry_defer_sec") or 0))
        return None

    doc = _FakeDoc(doc_metadata={"active_pipeline_hash": "ph-active"}, dataset_id=UUID(int=4))
    db = _FakeSession(doc, [])

    monkeypatch.setattr(jobs_mod, "SessionLocal", lambda: db, raising=True)
    monkeypatch.setattr(jobs_mod, "tenant_acquire", _fake_tenant_acquire, raising=True)
    monkeypatch.setattr(jobs_mod, "dataset_acquire", _fake_dataset_acquire, raising=True)
    monkeypatch.setattr(jobs_mod.settings, "TASK_KG_RETRY_DEFER_SEC", 11, raising=False)

    out = await jobs_mod.extract_kg_job(
        ctx={"redis": object()},
        tenant_id=str(UUID(int=3)),
        document_id=str(UUID(int=2)),
        requested_by="u",
    )

    assert out.get("reason") == "no_chunks"
    assert tenant_calls == [11]
    assert dataset_calls == [11]
