from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import BackgroundTasks


class _FakeQuery:
    def __init__(self, *, first=None, all_rows=None, delete_count: int = 0):  # noqa: ANN001
        self._first = first
        self._all = all_rows
        self._delete_count = int(delete_count or 0)
        self.delete_called = False

    def filter(self, *_a, **_k):  # noqa: ANN001
        return self

    def limit(self, *_a, **_k):  # noqa: ANN001
        return self

    def first(self):  # noqa: ANN001
        return self._first

    def all(self):  # noqa: ANN001
        return list(self._all or [])

    def delete(self, *_a, **_k):  # noqa: ANN001
        self.delete_called = True
        return self._delete_count


class _FakeDB:
    def __init__(self, *, doc_query: _FakeQuery, chunk_ids_query: _FakeQuery, chunk_delete_query: _FakeQuery, rel_delete_query: _FakeQuery):
        self.doc_query = doc_query
        self.chunk_ids_query = chunk_ids_query
        self.chunk_delete_query = chunk_delete_query
        self.rel_delete_query = rel_delete_query

        self.commits = 0
        self.rollbacks = 0

    def query(self, *args, **_k):  # noqa: ANN001
        from app.models.document import Document as DBDocument
        from app.models.document import DocumentChunk
        from app.rag.kg.models import KgRelation

        if args and args[0] is DBDocument:
            return self.doc_query
        if args and args[0] is DocumentChunk.id:
            return self.chunk_ids_query
        if args and args[0] is DocumentChunk:
            return self.chunk_delete_query
        if args and args[0] is KgRelation:
            return self.rel_delete_query
        raise AssertionError(f"Unexpected db.query args: {args!r}")

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def refresh(self, _obj) -> None:  # noqa: ANN001
        return


@pytest.mark.asyncio
async def test_retry_document_processing_preserve_existing_versions_cleans_kg(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    import app.api.v1.documents as docs_mod
    from app.api.v1.documents import retry_document_processing
    from app.services.dataset_service import DatasetService

    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(docs_mod, "audit_log_event", lambda *_a, **_k: None, raising=True)

    async def _noop_enqueue(*_a, **_k):  # noqa: ANN001
        await asyncio.sleep(0)  # Sonar S7503
        return None

    monkeypatch.setattr(docs_mod, "enqueue_document_processing", _noop_enqueue, raising=True)
    monkeypatch.setattr(docs_mod, "_compute_pipeline_hash", lambda _m: "newhash", raising=True)

    called: dict[str, object] = {"indexer_called": False, "chunk_ids": None}

    class _FakeIndexer:
        def __init__(self, _db):  # noqa: ANN001
            return

        def delete_event_indexes_for_chunks(self, **kwargs):  # noqa: ANN003
            called["indexer_called"] = True
            called["chunk_ids"] = list(kwargs.get("chunk_ids") or [])
            return {"events_deleted": 2, "entities_pruned": 0}

        def prune_orphan_entities(self, **_kwargs):  # noqa: ANN003
            return 0

    monkeypatch.setattr(docs_mod, "Indexer", _FakeIndexer, raising=True)

    tenant_id = UUID(int=1)
    document_id = UUID(int=2)
    chunk_ids = [UUID(int=10), UUID(int=11)]

    p = tmp_path / "doc.txt"
    p.write_text("hello", encoding="utf-8")

    doc = SimpleNamespace(
        id=document_id,
        tenant_id=tenant_id,
        dataset_id=None,
        status="completed",
        file_path=str(p),
        file_type="txt",
        filename="doc.txt",
        doc_metadata={
            "active_pipeline_hash": "activehash",
            "active_pipeline_ready": True,
        },
    )

    db = _FakeDB(
        doc_query=_FakeQuery(first=doc),
        chunk_ids_query=_FakeQuery(all_rows=[(chunk_ids[0],), (chunk_ids[1],)]),
        chunk_delete_query=_FakeQuery(delete_count=2),
        rel_delete_query=_FakeQuery(delete_count=3),
    )

    await retry_document_processing(
        document_id=document_id,
        background_tasks=BackgroundTasks(),
        force=True,
        skip_if_unchanged=False,
        tenant_id=tenant_id,
        account_id="u",
        db=db,
    )

    assert db.rel_delete_query.delete_called is True
    assert called["indexer_called"] is True
    assert called["chunk_ids"] == chunk_ids

