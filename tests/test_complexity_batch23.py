from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.api.schemas.dataset import DatasetRetentionPolicy
from app.services import retention_policy as rp
from app.services import web_crawler


class _SingleResultQuery:
    def __init__(self, value: object) -> None:
        self._value = value

    def filter(self, *_args, **_kwargs):  # noqa: ANN002, ANN003
        return self

    def first(self):  # noqa: ANN201
        return self._value


class _RetentionDB:
    def __init__(self, *, dataset_obj: object, document_obj: object) -> None:
        self._dataset_obj = dataset_obj
        self._document_obj = document_obj
        self.commits = 0
        self.rollbacks = 0

    def query(self, model):  # noqa: ANN001, ANN201
        if model is rp.Dataset:
            return _SingleResultQuery(self._dataset_obj)
        if model is rp.DBDocument:
            return _SingleResultQuery(self._document_obj)
        raise AssertionError(f"unexpected model: {model}")

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class _EmptyExpiredQuery:
    def limit(self, _n):  # noqa: ANN001, ANN201
        return self

    def all(self):  # noqa: ANN201
        return []


class _JobsDB:
    def __init__(self, document: object) -> None:
        self._document = document
        self.closed = False

    def query(self, model):  # noqa: ANN001, ANN201
        from app.tasks import jobs as jobs_module

        assert model is jobs_module.DBDocument
        return _SingleResultQuery(self._document)

    def close(self) -> None:
        self.closed = True

    def rollback(self) -> None:
        return None


def test_parse_sitemap_xml_splits_nested_sitemaps() -> None:
    pages, nested = web_crawler._parse_sitemap_xml(
        """
        <sitemapindex>
          <sitemap><loc>https://example.com/a.xml</loc></sitemap>
          <sitemap><loc>https://example.com/b.xml</loc></sitemap>
        </sitemapindex>
        """
    )

    assert pages == []
    assert nested == ["https://example.com/a.xml", "https://example.com/b.xml"]


def test_parse_sitemap_xml_falls_back_to_any_loc_elements() -> None:
    pages, nested = web_crawler._parse_sitemap_xml(
        """
        <feed>
          <entry><loc>https://example.com/page-1</loc></entry>
          <entry><loc>https://example.com/page-2</loc></entry>
        </feed>
        """
    )

    assert pages == ["https://example.com/page-1", "https://example.com/page-2"]
    assert nested == []


@pytest.mark.asyncio
async def test_run_dataset_retention_sweep_prunes_oldest_versions_after_keeping_active_and_newest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid4()
    dataset_id = uuid4()
    document_id = uuid4()
    now = datetime.now(timezone.utc)
    dataset_obj = SimpleNamespace(id=dataset_id, tenant_id=tenant_id, dataset_metadata={})
    document_obj = SimpleNamespace(id=document_id, tenant_id=tenant_id, dataset_id=dataset_id, doc_metadata={})
    db = _RetentionDB(dataset_obj=dataset_obj, document_obj=document_obj)
    deleted_hashes: list[str] = []

    monkeypatch.setattr(rp, "_expired_documents_query", lambda *_a, **_k: _EmptyExpiredQuery(), raising=True)
    monkeypatch.setattr(rp, "_candidate_documents_for_version_pruning", lambda *_a, **_k: [document_id], raising=True)
    monkeypatch.setattr(
        rp,
        "_list_document_versions_no_acl",
        lambda *_a, **_k: [
            rp._VersionRow("v4", f"{document_id}:v4", 1, now, now, False),
            rp._VersionRow("v3", f"{document_id}:v3", 1, now, now, False),
            rp._VersionRow("v2", f"{document_id}:v2", 1, now, now, True),
            rp._VersionRow("v1", f"{document_id}:v1", 1, now, now, False),
        ],
        raising=True,
    )
    monkeypatch.setattr(
        rp,
        "delete_document_version_best_effort",
        lambda *_a, **kwargs: deleted_hashes.append(str(kwargs["pipeline_hash"])) or {"ok": True},
        raising=True,
    )
    monkeypatch.setattr(rp, "audit_log_event", lambda *_a, **_k: None, raising=True)

    summary = await rp.run_dataset_retention_sweep(
        db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        policy=DatasetRetentionPolicy(enabled=True, action="archive", max_versions=2),
        dry_run=False,
        max_documents=10,
        max_versions_pruned=10,
        actor_id="system:retention",
        now=now,
    )

    assert summary["versions"]["documents_scanned"] == 1
    assert summary["versions"]["versions_pruned"] == 2
    assert deleted_hashes == ["v1", "v3"]


@pytest.mark.asyncio
async def test_run_dataset_retention_sweep_version_pruning_dry_run_counts_without_delete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid4()
    dataset_id = uuid4()
    document_id = uuid4()
    now = datetime.now(timezone.utc)
    dataset_obj = SimpleNamespace(id=dataset_id, tenant_id=tenant_id, dataset_metadata={})
    document_obj = SimpleNamespace(id=document_id, tenant_id=tenant_id, dataset_id=dataset_id, doc_metadata={})
    db = _RetentionDB(dataset_obj=dataset_obj, document_obj=document_obj)

    monkeypatch.setattr(rp, "_expired_documents_query", lambda *_a, **_k: _EmptyExpiredQuery(), raising=True)
    monkeypatch.setattr(rp, "_candidate_documents_for_version_pruning", lambda *_a, **_k: [document_id], raising=True)
    monkeypatch.setattr(
        rp,
        "_list_document_versions_no_acl",
        lambda *_a, **_k: [
            rp._VersionRow("v4", f"{document_id}:v4", 1, now, now, False),
            rp._VersionRow("v3", f"{document_id}:v3", 1, now, now, False),
            rp._VersionRow("v2", f"{document_id}:v2", 1, now, now, True),
            rp._VersionRow("v1", f"{document_id}:v1", 1, now, now, False),
        ],
        raising=True,
    )
    monkeypatch.setattr(
        rp,
        "delete_document_version_best_effort",
        lambda *_a, **_k: pytest.fail("dry-run must not delete versions"),
        raising=True,
    )
    monkeypatch.setattr(rp, "audit_log_event", lambda *_a, **_k: None, raising=True)

    summary = await rp.run_dataset_retention_sweep(
        db,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        policy=DatasetRetentionPolicy(enabled=True, action="archive", max_versions=2),
        dry_run=True,
        max_documents=10,
        max_versions_pruned=1,
        actor_id="system:retention",
        now=now,
    )

    assert summary["dry_run"] is True
    assert summary["versions"]["documents_scanned"] == 1
    assert summary["versions"]["versions_pruned"] == 1


@pytest.mark.asyncio
async def test_process_document_job_reports_download_failed_but_persists_raw_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:  # noqa: ANN001
    from app.tasks import jobs

    tenant_id = uuid4()
    document_id = uuid4()
    dataset_id = uuid4()
    document = SimpleNamespace(
        id=document_id,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        doc_metadata={"source_storage_backend": "object_storage"},
        file_type="pdf",
        file_path="s3://bucket/documents/file.pdf",
        status="pending",
        error_message=None,
    )
    db = _JobsDB(document)

    class _Store:
        def download_object_to_path(self, *, object_name, destination, max_bytes):  # noqa: ANN001
            raise RuntimeError("download exploded")

    async def _acquire(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        return None

    async def _lock(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        return True

    async def _release(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        return None

    async def _update_status(_db, _tid, _did, status, _progress, _stage, *, error_message=None):  # noqa: ANN001, ANN202
        document.status = status
        document.error_message = error_message

    monkeypatch.setattr(jobs, "SessionLocal", lambda: db, raising=True)
    monkeypatch.setattr(jobs.settings, "OBJECT_STORAGE_ENABLED", True, raising=False)
    monkeypatch.setattr(jobs.settings, "UPLOAD_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(jobs, "_task_queue_redis_or_retry", lambda *_a, **_k: object(), raising=True)
    monkeypatch.setattr(jobs, "tenant_acquire", _acquire, raising=True)
    monkeypatch.setattr(jobs, "dataset_acquire", _acquire, raising=True)
    monkeypatch.setattr(jobs, "_acquire_task_lock_or_retry", _lock, raising=True)
    monkeypatch.setattr(jobs, "release_lock", _release, raising=True)
    monkeypatch.setattr(jobs, "dataset_release", _release, raising=True)
    monkeypatch.setattr(jobs, "tenant_release", _release, raising=True)
    monkeypatch.setattr(
        jobs,
        "resolve_document_object_reference",
        lambda *_a, **_k: (_Store(), SimpleNamespace(object_name="documents/file.pdf")),
        raising=True,
    )
    monkeypatch.setattr(jobs.document_processor, "_update_status", _update_status, raising=True)

    result = await jobs.process_document_job(
        {"job_try": 1, "redis": object()},
        str(tenant_id),
        str(document_id),
        "member-1",
    )

    assert result["ok"] is False
    assert result["reason"] == "download_failed"
    assert document.status == "failed"
    assert document.error_message == "download exploded"
    assert db.closed is True
