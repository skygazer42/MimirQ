from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

from tests.helpers.async_utils import yield_control


class _FakeDB:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def test_run_knowledge_asset_retention_dry_run(monkeypatch):  # noqa: ANN001
    from app.services import retention_jobs

    db = _FakeDB()
    tenant_id = uuid.uuid4()
    now = datetime(2026, 3, 7, 0, 0, 0, tzinfo=UTC)

    planned_rows = [
        {
            "document_id": uuid.uuid4(),
            "dataset_id": uuid.uuid4(),
            "lifecycle_ts": datetime(2025, 11, 1, tzinfo=UTC),
            "lifecycle_state": "archived",
        },
        {
            "document_id": uuid.uuid4(),
            "dataset_id": uuid.uuid4(),
            "lifecycle_ts": datetime(2025, 11, 2, tzinfo=UTC),
            "lifecycle_state": "disabled",
        },
    ]

    monkeypatch.setattr(retention_jobs, "plan_knowledge_asset_purge", lambda *_a, **_k: planned_rows, raising=True)

    async def _fail_delete(**_k):  # noqa: ANN001
        await yield_control()
        raise AssertionError("dry-run must not invoke document delete lifecycle")

    monkeypatch.setattr(retention_jobs, "_delete_document_lifecycle", _fail_delete, raising=False)

    captured: list[dict] = []

    def _audit(_db, **kwargs):  # noqa: ANN001
        captured.append(kwargs)

    monkeypatch.setattr(retention_jobs, "audit_log_event", _audit, raising=True)

    out = asyncio.run(
        retention_jobs.run_knowledge_asset_retention(
            db,
            tenant_id=tenant_id,
            retention_days=90,
            max_delete=10,
            dry_run=True,
            actor_id="system:test",
            now=now,
        )
    )

    assert out.get("dry_run") is True
    assert out.get("eligible") == 2
    assert out.get("deleted") == 0
    assert out.get("artifact_scopes") == ["documents", "chunks", "kg", "vectors", "object_assets"]
    assert len(captured) == 1
    assert captured[0].get("action") == "knowledge.assets.retention"
    assert db.commits == 1


def test_run_knowledge_asset_retention_execute(monkeypatch):  # noqa: ANN001
    from app.services import retention_jobs

    db = _FakeDB()
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    now = datetime(2026, 3, 7, 0, 0, 0, tzinfo=UTC)

    doc1 = uuid.uuid4()
    doc2 = uuid.uuid4()
    planned_rows = [
        {
            "document_id": doc1,
            "dataset_id": dataset_id,
            "lifecycle_ts": datetime(2025, 11, 1, tzinfo=UTC),
            "lifecycle_state": "archived",
        },
        {
            "document_id": doc2,
            "dataset_id": dataset_id,
            "lifecycle_ts": datetime(2025, 11, 2, tzinfo=UTC),
            "lifecycle_state": "archived",
        },
    ]

    monkeypatch.setattr(retention_jobs, "plan_knowledge_asset_purge", lambda *_a, **_k: planned_rows, raising=True)

    deleted_ids: list[uuid.UUID] = []

    async def _delete_document_lifecycle(*, document_id, tenant_id, account_id, db, enforce_permissions):  # noqa: ANN001
        await yield_control()
        assert tenant_id
        assert account_id == "system:test"
        assert enforce_permissions is False
        deleted_ids.append(document_id)
        return None

    monkeypatch.setattr(retention_jobs, "_delete_document_lifecycle", _delete_document_lifecycle, raising=False)
    monkeypatch.setattr(retention_jobs, "audit_log_event", lambda *_a, **_k: None, raising=True)

    out = asyncio.run(
        retention_jobs.run_knowledge_asset_retention(
            db,
            tenant_id=tenant_id,
            retention_days=30,
            max_delete=10,
            dry_run=False,
            dataset_id=dataset_id,
            lifecycle_state="archived",
            actor_id="system:test",
            now=now,
        )
    )

    assert out.get("dry_run") is False
    assert out.get("eligible") == 2
    assert out.get("deleted") == 2
    assert out.get("dataset_id") == str(dataset_id)
    assert out.get("lifecycle_state") == "archived"
    assert deleted_ids == [doc1, doc2]
    assert db.commits == 1
