from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import pytest


@dataclass
class _FakeDocument:
    id: uuid.UUID
    tenant_id: uuid.UUID
    dataset_id: uuid.UUID | None
    status: str = "completed"
    processing_progress: int = 100
    current_stage: str = "done"
    error_message: str | None = None
    doc_metadata: dict | None = None
    file_path: str = "manual://test"
    file_type: str = "pdf"
    file_size: int = 0


class _FakeDataset:
    def __init__(self, *, tenant_id: uuid.UUID, dataset_id: uuid.UUID, updated_at: datetime) -> None:
        self.tenant_id = tenant_id
        self.id = dataset_id
        self.updated_at = updated_at


class _FakeQuery:
    def __init__(self, *, first_obj=None):  # noqa: ANN001
        self._first = first_obj

    def filter(self, *_a, **_k):  # noqa: ANN001
        return self

    def first(self):  # noqa: ANN001
        return self._first

    def all(self):  # noqa: ANN001
        return []

    def delete(self, **_k) -> int:  # noqa: ANN003
        return 0


class _FakeDB:
    def __init__(self, queries):  # noqa: ANN001
        self._queries = list(queries)
        self.commits = 0

    def query(self, *_a, **_k):  # noqa: ANN001
        if not self._queries:
            raise AssertionError("Unexpected db.query call")
        return self._queries.pop(0)

    def delete(self, *_a, **_k) -> None:  # noqa: ANN001
        return None

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        return None

    def refresh(self, *_a, **_k) -> None:  # noqa: ANN001
        return None


@pytest.mark.asyncio
async def test_delete_document_lifecycle_touches_dataset_updated_at(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services.document_lifecycle_service as document_lifecycle_service
    from app.core.config import settings
    from app.services.dataset_service import DatasetService
    from app.services.document_lifecycle_service import _delete_document_lifecycle

    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(document_lifecycle_service, "audit_log_event", lambda *_a, **_k: None, raising=True)

    monkeypatch.setattr(settings, "TASK_QUEUE_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "MINIO_ENABLED", False, raising=False)

    class _StubIndexer:
        def __init__(self, _db):  # noqa: ANN001
            return

        def delete_chunk_indexes(self, **_k) -> None:  # noqa: ANN003
            return None

        def delete_event_indexes(self, **_k) -> None:  # noqa: ANN003
            return None

    monkeypatch.setattr(document_lifecycle_service, "Indexer", _StubIndexer, raising=True)

    tenant_id = uuid.UUID(int=1)
    dataset_id = uuid.UUID(int=2)
    document_id = uuid.UUID(int=3)

    doc = _FakeDocument(id=document_id, tenant_id=tenant_id, dataset_id=dataset_id)
    ds = _FakeDataset(
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        updated_at=datetime(2020, 1, 1, tzinfo=UTC),
    )
    initial_updated_at = ds.updated_at

    db = _FakeDB(
        queries=[
            _FakeQuery(first_obj=doc),  # document lookup
            _FakeQuery(first_obj=ds),  # dataset lookup for updated_at touch
            _FakeQuery(first_obj=None),  # KgRelation query (best-effort cleanup)
        ]
    )

    await _delete_document_lifecycle(
        document_id=document_id,
        tenant_id=tenant_id,
        account_id="test-account",
        db=db,
        enforce_permissions=False,
    )

    assert ds.updated_at != initial_updated_at
