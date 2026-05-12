from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

import pytest


class _FakeQuery:
    def __init__(self, *, first=None, all_rows=None, delete_count: int = 0):  # noqa: ANN001
        self._first = first
        self._all = all_rows
        self._delete_count = int(delete_count or 0)
        self.delete_called = False

    def filter(self, *_a, **_k):  # noqa: ANN001
        return self

    def all(self):  # noqa: ANN001
        return list(self._all or [])

    def first(self):  # noqa: ANN001
        return self._first

    def delete(self, *_a, **_k):  # noqa: ANN001
        self.delete_called = True
        return self._delete_count


class _FakeDB:
    def __init__(self, queries):  # noqa: ANN001
        self._queries = list(queries)

    def query(self, *_a, **_k):  # noqa: ANN001
        if not self._queries:
            raise AssertionError("Unexpected db.query call")
        return self._queries.pop(0)

    def commit(self) -> None:
        return

    def rollback(self) -> None:
        return


@pytest.mark.asyncio
async def test_delete_document_version_cleans_kg_relations_and_events(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.document_versions as doc_versions_mod
    from app.api.v1.document_versions import delete_document_version
    from app.services.dataset_service import DatasetService

    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(DatasetService, "get_dataset", lambda *_a, **_k: object(), raising=True)
    monkeypatch.setattr(DatasetService, "assert_dataset_writable", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(doc_versions_mod, "audit_log_event", lambda *_a, **_k: None, raising=True)

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

    monkeypatch.setattr(doc_versions_mod, "Indexer", _FakeIndexer, raising=True)

    tenant_id = UUID(int=1)
    document_id = UUID(int=2)
    chunk_ids = [UUID(int=10), UUID(int=11)]

    doc = SimpleNamespace(
        id=document_id,
        tenant_id=tenant_id,
        dataset_id=None,
        status="completed",
        doc_metadata={"pipeline_hash": "current", "active_pipeline_hash": "active"},
    )

    doc_query = _FakeQuery(first=doc)
    chunk_ids_query = _FakeQuery(all_rows=[(chunk_ids[0],), (chunk_ids[1],)])
    chunk_delete_query = _FakeQuery(delete_count=2)
    rel_delete_query = _FakeQuery(delete_count=3)
    db = _FakeDB([doc_query, chunk_ids_query, chunk_delete_query, rel_delete_query])

    await delete_document_version(
        document_id=document_id,
        pipeline_hash="old",
        tenant_id=tenant_id,
        account_id="u",
        db=db,
    )

    # Must clean KG artifacts for the deleted pipeline version.
    assert rel_delete_query.delete_called is True
    assert called["indexer_called"] is True
    assert called["chunk_ids"] == chunk_ids
