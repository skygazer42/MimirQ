import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import ANY

import pytest


def test_documents_exports_delegate_to_shared_services() -> None:
    from app.api.v1 import documents
    from app.services import document_access_service, document_lifecycle_service

    assert documents.NO_DOCUMENT_ACCESS_DETAIL == document_access_service.NO_DOCUMENT_ACCESS_DETAIL
    assert documents._assert_document_acl_readable is document_access_service.assert_document_acl_readable
    assert documents._get_document_for_lifecycle is document_access_service.get_document_for_lifecycle
    assert documents._assert_document_writable_for_lifecycle is document_access_service.assert_document_writable_for_lifecycle
    assert documents._get_document_for_delete is document_lifecycle_service._get_document_for_delete
    assert documents._delete_document_file is document_lifecycle_service._delete_document_file
    assert documents._delete_document_lifecycle is document_lifecycle_service._delete_document_lifecycle


class _LifecycleDB:
    def __init__(self, document, *, fail_commit_at: int | None = None) -> None:  # noqa: ANN001
        self.document = document
        self.fail_commit_at = fail_commit_at
        self.commit_calls = 0
        self.rollback_calls = 0
        self.refresh_calls = 0
        self.delete_calls = 0
        self.deleted = False
        self._persisted = self._snapshot()

    def _snapshot(self) -> dict[str, object]:
        return {
            "status": getattr(self.document, "status", None),
            "current_stage": getattr(self.document, "current_stage", None),
            "error_message": getattr(self.document, "error_message", None),
            "processing_progress": getattr(self.document, "processing_progress", None),
            "doc_metadata": dict(getattr(self.document, "doc_metadata", None) or {}),
            "deleted": self.deleted,
        }

    def _restore(self, snapshot: dict[str, object]) -> None:
        self.document.status = snapshot["status"]
        self.document.current_stage = snapshot["current_stage"]
        self.document.error_message = snapshot["error_message"]
        self.document.processing_progress = snapshot["processing_progress"]
        self.document.doc_metadata = dict(snapshot["doc_metadata"] or {})
        self.deleted = bool(snapshot["deleted"])

    def commit(self) -> None:
        self.commit_calls += 1
        if self.fail_commit_at is not None and self.commit_calls == self.fail_commit_at:
            raise RuntimeError("commit failed")
        self._persisted = self._snapshot()

    def refresh(self, _obj) -> None:  # noqa: ANN001
        self.refresh_calls += 1

    def rollback(self) -> None:
        self.rollback_calls += 1
        self._restore(self._persisted)

    def delete(self, _obj) -> None:  # noqa: ANN001
        self.delete_calls += 1
        self.deleted = True


@pytest.mark.asyncio
async def test_delete_document_lifecycle_defaults_to_membership_enforcement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import document_lifecycle_service as dls

    tenant_id = uuid.uuid4()
    document_id = uuid.uuid4()
    document = SimpleNamespace(
        id=document_id,
        tenant_id=tenant_id,
        dataset_id=None,
        status="completed",
        current_stage=None,
        error_message=None,
        processing_progress=100,
        file_type="pdf",
        file_size=12,
        file_path="manual://placeholder",
        doc_metadata={},
    )
    db = _LifecycleDB(document)
    membership_calls: list[tuple[uuid.UUID, str]] = []

    async def _noop_async(**_kwargs) -> None:  # noqa: ANN003
        return None

    monkeypatch.setattr(dls.DatasetService, "ensure_member", lambda _db, tid, aid: membership_calls.append((tid, aid)), raising=True)
    monkeypatch.setattr(dls, "_get_document_for_delete", lambda *_a, **_k: document, raising=True)
    monkeypatch.setattr(dls, "_assert_document_delete_permission", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(dls, "_abort_document_tasks_before_delete", _noop_async, raising=True)
    monkeypatch.setattr(dls, "_delete_document_minio_images", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(dls, "_delete_document_table_store", lambda **_k: None, raising=True)
    monkeypatch.setattr(dls, "_delete_document_file", lambda **_k: None, raising=True)
    monkeypatch.setattr(dls, "_touch_dataset_updated_after_delete", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(dls, "_cleanup_document_kg_artifacts", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(dls, "audit_log_event", lambda *_a, **_k: None, raising=True)

    class _Indexer:
        def __init__(self, _db) -> None:  # noqa: ANN001
            return None

        def delete_chunk_indexes(self, **_kwargs) -> None:
            return None

    monkeypatch.setattr(dls, "_get_indexer_class", lambda: _Indexer, raising=True)

    await dls._delete_document_lifecycle(
        document_id=document_id,
        tenant_id=tenant_id,
        account_id="api-user",
        db=db,
    )

    assert membership_calls == [(tenant_id, "api-user")]


@pytest.mark.asyncio
async def test_delete_document_lifecycle_persists_deleting_state_before_external_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import document_lifecycle_service as dls

    tenant_id = uuid.uuid4()
    document_id = uuid.uuid4()
    document = SimpleNamespace(
        id=document_id,
        tenant_id=tenant_id,
        dataset_id=None,
        status="completed",
        current_stage=None,
        error_message=None,
        processing_progress=100,
        file_type="pdf",
        file_size=12,
        file_path="manual://placeholder",
        doc_metadata={},
    )
    db = _LifecycleDB(document, fail_commit_at=2)
    cleanup_steps: list[str] = []

    async def _noop_async(**_kwargs) -> None:  # noqa: ANN003
        return None

    monkeypatch.setattr(dls.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(dls, "_get_document_for_delete", lambda *_a, **_k: document, raising=True)
    monkeypatch.setattr(dls, "_assert_document_delete_permission", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(dls, "_abort_document_tasks_before_delete", _noop_async, raising=True)
    monkeypatch.setattr(dls, "_delete_document_minio_images", lambda *_a, **_k: cleanup_steps.append("images"), raising=True)
    monkeypatch.setattr(dls, "_delete_document_table_store", lambda **_k: cleanup_steps.append("table_store"), raising=True)
    monkeypatch.setattr(dls, "_delete_document_file", lambda **_k: cleanup_steps.append("file"), raising=True)
    monkeypatch.setattr(dls, "_cleanup_document_kg_artifacts", lambda *_a, **_k: cleanup_steps.append("kg"), raising=True)
    monkeypatch.setattr(dls, "audit_log_event", lambda *_a, **_k: None, raising=True)

    monkeypatch.setattr(dls, "_touch_dataset_updated_after_delete", lambda *_a, **_k: cleanup_steps.append("touch_dataset"), raising=True)

    class _Indexer:
        def __init__(self, _db) -> None:  # noqa: ANN001
            return None

        def delete_chunk_indexes(self, **_kwargs) -> None:
            cleanup_steps.append("vectors")

        def delete_event_indexes(self, **_kwargs) -> None:
            cleanup_steps.append("event_vectors")

    monkeypatch.setattr(dls, "_get_indexer_class", lambda: _Indexer, raising=True)

    with pytest.raises(RuntimeError, match="commit failed"):
        await dls._delete_document_lifecycle(
            document_id=document_id,
            tenant_id=tenant_id,
            account_id="system:retention",
            db=db,
            enforce_permissions=False,
            enforce_membership=False,
        )

    assert cleanup_steps == ["images", "vectors", "table_store", "file", "kg", "touch_dataset"]
    assert db.commit_calls == 2
    assert db.rollback_calls == 1
    assert db.deleted is False
    assert document.status == "deleting"
    assert document.current_stage == "deleting"
    assert document.doc_metadata["deletion"]["state"] == "deleting"
    assert document.doc_metadata["deletion"]["requested_by"] == "system:retention"


@pytest.mark.asyncio
async def test_delete_document_lifecycle_keeps_tombstone_when_minio_cleanup_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import document_lifecycle_service as dls

    tenant_id = uuid.uuid4()
    document_id = uuid.uuid4()
    document = SimpleNamespace(
        id=document_id,
        tenant_id=tenant_id,
        dataset_id=None,
        status="completed",
        current_stage=None,
        error_message=None,
        processing_progress=100,
        file_type="pdf",
        file_size=12,
        file_path="manual://placeholder",
        doc_metadata={},
    )
    db = _LifecycleDB(document)

    async def _noop_async(**_kwargs) -> None:  # noqa: ANN003
        return None

    def _fail_cleanup(*_args, **_kwargs) -> None:  # noqa: ANN002, ANN003
        raise RuntimeError("MinIO delete image failed")

    monkeypatch.setattr(dls, "_get_document_for_delete", lambda *_a, **_k: document, raising=True)
    monkeypatch.setattr(dls, "_assert_document_delete_permission", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(dls, "_abort_document_tasks_before_delete", _noop_async, raising=True)
    monkeypatch.setattr(dls, "_delete_document_minio_images", _fail_cleanup, raising=True)

    with pytest.raises(RuntimeError, match="MinIO delete image failed"):
        await dls._delete_document_lifecycle(
            document_id=document_id,
            tenant_id=tenant_id,
            account_id="system:retention",
            db=db,
            enforce_permissions=False,
            enforce_membership=False,
        )

    assert db.delete_calls == 0
    assert db.rollback_calls == 1
    assert document.status == "deleting"
    assert document.doc_metadata["deletion"]["state"] == "deleting"


def test_minio_delete_helpers_propagate_client_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.storage.object.minio import MinIOService

    class _FailingClient:
        def remove_object(self, **_kwargs) -> None:
            raise OSError("storage unavailable")

    service = MinIOService()
    monkeypatch.setattr(service, "_get_client", lambda: _FailingClient(), raising=True)
    monkeypatch.setattr(service, "_log_metric", lambda *_a, **_k: None, raising=True)

    with pytest.raises(RuntimeError, match="MinIO delete image failed"):
        service.delete_image("dataset-chunk")
    with pytest.raises(RuntimeError, match="MinIO delete object failed"):
        service.delete_object(object_name="documents/t/d/doc.pdf")


def test_cleanup_document_kg_artifacts_propagates_event_index_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import document_lifecycle_service as dls

    tenant_id = uuid.uuid4()
    document_id = uuid.uuid4()

    class _Query:
        def filter(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
            return self

        def delete(self, **_kwargs) -> None:
            return None

    class _DB:
        def __init__(self) -> None:
            self.commit_calls = 0
            self.rollback_calls = 0

        def query(self, _model):  # noqa: ANN001
            return _Query()

        def commit(self) -> None:
            self.commit_calls += 1

        def rollback(self) -> None:
            self.rollback_calls += 1

    class _Indexer:
        def __init__(self, _db) -> None:  # noqa: ANN001
            return None

        def delete_event_indexes(self, **_kwargs) -> None:
            assert _kwargs["strict"] is True
            raise RuntimeError("event index cleanup failed")

    monkeypatch.setattr(dls, "_get_indexer_class", lambda: _Indexer, raising=True)

    with pytest.raises(RuntimeError, match="event index cleanup failed"):
        dls._cleanup_document_kg_artifacts(_DB(), tenant_id=tenant_id, document_id=document_id)


def test_delete_document_file_skips_malformed_minio_uri(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import document_lifecycle_service as dls

    monkeypatch.setattr(dls.settings, "MINIO_ENABLED", True, raising=False)
    monkeypatch.setattr(
        dls,
        "parse_minio_uri",
        lambda *_a, **_k: (_ for _ in ()).throw(ValueError("bad uri")),
        raising=True,
    )
    monkeypatch.setattr(
        dls.minio_service,
        "delete_object",
        lambda **_kwargs: pytest.fail("malformed URI must not reach object deletion"),
        raising=True,
    )
    document = SimpleNamespace(
        id=uuid.uuid4(),
        dataset_id=uuid.uuid4(),
        file_type="pdf",
        file_path="minio://missing-object",
    )

    dls._delete_document_file(tenant_id=uuid.uuid4(), document=document)


@pytest.mark.asyncio
async def test_rtbf_cascade_uses_system_membership_bypass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import rtbf_cascade as cascade

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    document_id = uuid.uuid4()
    now = datetime.now(UTC)
    delete_calls: list[dict[str, object]] = []

    async def _fake_delete_document_lifecycle(**kwargs):  # noqa: ANN003
        delete_calls.append(kwargs)

    monkeypatch.setattr(
        cascade,
        "_list_rtbf_documents",
        lambda *_a, **_k: [
            {
                "document_id": document_id,
                "dataset_id": dataset_id,
                "filename": "doc.pdf",
                "match_reasons": ["owner_id"],
            }
        ],
        raising=True,
    )
    monkeypatch.setattr(cascade, "_resolve_delete_document_lifecycle", lambda: _fake_delete_document_lifecycle, raising=True)
    monkeypatch.setattr(cascade, "_invalidate_dataset_caches", lambda *_a, **_k: 1, raising=True)
    monkeypatch.setattr(cascade, "audit_log_event", lambda *_a, **_k: None, raising=True)

    class _DB:
        def commit(self) -> None:
            return None

    summary = await cascade.run_rtbf_cascade(
        _DB(),
        tenant_id=tenant_id,
        subject_account_id="subject-account",
        dry_run=False,
        actor_id="system:rtbf",
        now=now,
    )

    assert summary["deleted"] == 1
    assert delete_calls == [
        {
            "document_id": document_id,
            "tenant_id": tenant_id,
            "account_id": "system:rtbf",
            "db": ANY,
            "enforce_permissions": False,
            "enforce_membership": False,
        }
    ]


@pytest.mark.asyncio
async def test_knowledge_asset_retention_uses_system_membership_bypass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import retention_jobs

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    document_id = uuid.uuid4()
    now = datetime.now(UTC)
    delete_calls: list[dict[str, object]] = []

    async def _fake_delete_document_lifecycle(**kwargs):  # noqa: ANN003
        delete_calls.append(kwargs)

    monkeypatch.setattr(
        retention_jobs,
        "plan_knowledge_asset_purge",
        lambda *_a, **_k: [{"document_id": document_id, "dataset_id": dataset_id, "lifecycle_state": "archived"}],
        raising=True,
    )
    monkeypatch.setattr(retention_jobs, "_resolve_delete_document_lifecycle", lambda: _fake_delete_document_lifecycle, raising=True)
    monkeypatch.setattr(retention_jobs, "audit_log_event", lambda *_a, **_k: None, raising=True)

    class _DB:
        def commit(self) -> None:
            return None

    summary = await retention_jobs.run_knowledge_asset_retention(
        _DB(),
        tenant_id=tenant_id,
        retention_days=30,
        max_delete=10,
        dry_run=False,
        dataset_id=dataset_id,
        actor_id="system:retention",
        now=now,
    )

    assert summary["deleted"] == 1
    assert delete_calls == [
        {
            "document_id": document_id,
            "tenant_id": tenant_id,
            "account_id": "system:retention",
            "db": ANY,
            "enforce_permissions": False,
            "enforce_membership": False,
        }
    ]
