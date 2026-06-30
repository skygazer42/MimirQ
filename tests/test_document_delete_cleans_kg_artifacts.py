from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID

import pytest


class _FakeQuery:
    def __init__(self, *, first=None, delete_count: int = 0):  # noqa: ANN001
        self._first = first
        self._delete_count = int(delete_count or 0)
        self.delete_called = False

    def filter(self, *_a, **_k):  # noqa: ANN001
        return self

    def first(self):  # noqa: ANN001
        return self._first

    def all(self):  # noqa: ANN001
        return []

    def delete(self, *_a, **_k):  # noqa: ANN001
        self.delete_called = True
        return self._delete_count


class _FakeDB:
    def __init__(self, queries):  # noqa: ANN001
        self._queries = list(queries)
        self.deleted = []
        self.commits = 0

    def query(self, *_a, **_k):  # noqa: ANN001
        if not self._queries:
            raise AssertionError("Unexpected db.query call")
        return self._queries.pop(0)

    def delete(self, obj) -> None:  # noqa: ANN001
        self.deleted.append(obj)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        return

    def refresh(self, _obj) -> None:  # noqa: ANN001
        return


@pytest.mark.asyncio
async def test_delete_document_cleans_kg_relations_and_events(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.documents as docs_mod
    import app.services.document_lifecycle_service as lifecycle_mod
    from app.api.v1.documents import delete_document
    from app.core import config as config_mod
    from app.services.dataset_service import DatasetService

    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(docs_mod, "audit_log_event", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(lifecycle_mod, "audit_log_event", lambda *_a, **_k: None, raising=True)

    monkeypatch.setattr(config_mod.settings, "MINIO_ENABLED", False, raising=False)
    monkeypatch.setattr(config_mod.settings, "TASK_QUEUE_ENABLED", False, raising=False)

    called: dict[str, object] = {"event_delete_called": False, "kwargs": None}

    class _FakeIndexer:
        def __init__(self, _db):  # noqa: ANN001
            return

        def delete_all(self, **_kwargs):  # noqa: ANN003
            return

        def delete_chunk_indexes(self, **_kwargs):  # noqa: ANN003
            return

        def delete_event_indexes(self, **kwargs):  # noqa: ANN003
            called["event_delete_called"] = True
            called["kwargs"] = dict(kwargs)
            return {"events_deleted": 1, "entities_pruned": 0}

        def prune_orphan_entities(self, **_kwargs):  # noqa: ANN003
            return 0

    monkeypatch.setattr(docs_mod, "Indexer", _FakeIndexer, raising=True)
    monkeypatch.setattr(lifecycle_mod, "Indexer", _FakeIndexer, raising=True)

    tenant_id = UUID(int=1)
    document_id = UUID(int=2)

    doc = SimpleNamespace(
        id=document_id,
        tenant_id=tenant_id,
        dataset_id=None,
        status="completed",
        doc_metadata={},
        file_type="txt",
        file_size=123,
        file_path="",
    )

    doc_query = _FakeQuery(first=doc)
    rel_delete_query = _FakeQuery(delete_count=2)
    db = _FakeDB([doc_query, rel_delete_query])

    await delete_document(
        document_id=document_id,
        tenant_id=tenant_id,
        account_id="u",
        db=db,
    )

    assert rel_delete_query.delete_called is True
    assert called["event_delete_called"] is True
    assert called["kwargs"]["document_id"] == document_id
    assert called["kwargs"]["tenant_id"] == tenant_id
    assert called["kwargs"]["prune_orphan_entities"] is True
