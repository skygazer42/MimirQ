
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import ANY

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db
from app.models.dataset import DatasetPermissionEnum


class _DummyDB:
    def commit(self) -> None:
        return None

    def refresh(self, _obj) -> None:  # noqa: ANN001
        return None

    def rollback(self) -> None:
        return None


def _override_get_db():  # noqa: ANN202
    yield _DummyDB()


class _CommitTrackingDB(_DummyDB):
    def __init__(self, *, dataset_obj, tracked_docs, fail_commit_at: int | None = None) -> None:  # noqa: ANN001
        self._dataset_obj = dataset_obj
        self._tracked_docs = list(tracked_docs)
        self._snapshots = [getattr(doc, "archived_at", None) for doc in self._tracked_docs]
        self._fail_commit_at = fail_commit_at
        self.commit_calls = 0
        self.rollback_calls = 0

    def query(self, _model):  # noqa: ANN001, ANN201
        dataset_obj = self._dataset_obj

        class _DatasetQuery:
            def filter(self, *_args, **_kwargs):  # noqa: ANN001
                return self

            def first(self):  # noqa: ANN201
                return dataset_obj

        return _DatasetQuery()

    def commit(self) -> None:
        self.commit_calls += 1
        if self._fail_commit_at is not None and self.commit_calls == self._fail_commit_at:
            raise RuntimeError("commit failed")
        self._snapshots = [getattr(doc, "archived_at", None) for doc in self._tracked_docs]

    def rollback(self) -> None:
        self.rollback_calls += 1
        for doc, archived_at in zip(self._tracked_docs, self._snapshots, strict=False):
            doc.archived_at = archived_at


def test_retention_policy_metadata_helpers_round_trip() -> None:
    from app.api.schemas.dataset import DatasetRetentionPolicy
    from app.services.retention_policy import (
        parse_retention_policy_from_metadata,
        upsert_retention_policy_metadata,
    )

    meta: dict[str, object] = {}
    policy = DatasetRetentionPolicy(enabled=True, action="archive", max_age_days=90, max_versions=3)

    changed = upsert_retention_policy_metadata(meta, policy=policy, replace=True)
    assert changed is True
    parsed = parse_retention_policy_from_metadata(meta)
    assert parsed is not None
    assert parsed.enabled is True
    assert parsed.action == "archive"
    assert parsed.max_age_days == 90
    assert parsed.max_versions == 3

    # Idempotent
    changed2 = upsert_retention_policy_metadata(meta, policy=policy, replace=True)
    assert changed2 is False

    # Remove only when replace=true
    changed3 = upsert_retention_policy_metadata(meta, policy=None, replace=False)
    assert changed3 is False
    assert "retention_policy" in meta

    changed4 = upsert_retention_policy_metadata(meta, policy=None, replace=True)
    assert changed4 is True
    assert "retention_policy" not in meta


def test_create_dataset_returns_retention_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.datasets as ds_api
    from app.api.schemas.dataset import DatasetOut

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    now = datetime.now(UTC)

    dataset_obj = SimpleNamespace(
        id=dataset_id,
        tenant_id=tenant_id,
        name="DS",
        description=None,
        permission=DatasetPermissionEnum.ALL_TEAM_MEMBERS,
        owner_id="owner",
        dataset_metadata={},
        created_at=now,
        updated_at=now,
    )

    monkeypatch.setattr(ds_api, "audit_log_event", lambda *_a, **_k: None, raising=False)

    def _create_dataset(*, db, tenant_id, name, description, permission, owner_id, partial_members, partial_groups):  # noqa: ANN001
        assert tenant_id == dataset_obj.tenant_id
        assert owner_id == "owner"
        assert permission == DatasetPermissionEnum.ALL_TEAM_MEMBERS
        return dataset_obj

    monkeypatch.setattr(ds_api.DatasetService, "create_dataset", _create_dataset, raising=True)

    def _override_get_tenant_id() -> uuid.UUID:
        return tenant_id

    def _override_get_current_account_id() -> str:
        return "owner"

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.post("/api/v1/datasets", status_code=201, response_model=DatasetOut)(ds_api.create_dataset)
    client = TestClient(app)

    res = client.post(
        "/api/v1/datasets",
        json={
            "name": "DS",
            "permission": "all_team_members",
            "retention_policy": {"enabled": True, "action": "archive", "max_age_days": 90, "max_versions": 2},
        },
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body.get("retention_policy", {}).get("enabled") is True
    assert body.get("retention_policy", {}).get("action") == "archive"
    assert body.get("retention_policy", {}).get("max_age_days") == 90
    assert body.get("retention_policy", {}).get("max_versions") == 2

    # Stored in datasets.metadata (best-effort).
    stored = dict(getattr(dataset_obj, "dataset_metadata", None) or {})
    assert stored.get("retention_policy", {}).get("enabled") is True


def test_get_dataset_returns_retention_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.datasets as ds_api
    from app.api.schemas.dataset import DatasetOut

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    now = datetime.now(UTC)

    dataset_obj = SimpleNamespace(
        id=dataset_id,
        tenant_id=tenant_id,
        name="DS",
        description=None,
        permission=DatasetPermissionEnum.ALL_TEAM_MEMBERS,
        owner_id="owner",
        dataset_metadata={"retention_policy": {"enabled": True, "action": "delete", "max_inactive_days": 30}},
        created_at=now,
        updated_at=now,
    )

    monkeypatch.setattr(ds_api.DatasetService, "get_dataset", lambda *_a, **_k: dataset_obj, raising=True)
    monkeypatch.setattr(ds_api.DatasetService, "assert_dataset_readable", lambda *_a, **_k: None, raising=True)

    def _override_get_tenant_id() -> uuid.UUID:
        return tenant_id

    def _override_get_current_account_id() -> str:
        return "owner"

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.get("/api/v1/datasets/{dataset_id}", response_model=DatasetOut)(ds_api.get_dataset)
    client = TestClient(app)

    res = client.get(f"/api/v1/datasets/{dataset_id}")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body.get("retention_policy", {}).get("enabled") is True
    assert body.get("retention_policy", {}).get("action") == "delete"
    assert body.get("retention_policy", {}).get("max_inactive_days") == 30


@pytest.mark.asyncio
async def test_run_dataset_retention_sweep_dry_run_summarizes_eligible_documents(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.schemas.dataset import DatasetRetentionPolicy
    from app.services import retention_policy as rp

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    now = datetime.now(UTC)
    dataset_obj = SimpleNamespace(id=dataset_id, tenant_id=tenant_id, dataset_metadata={})
    expired_docs = [
        SimpleNamespace(id=uuid.uuid4(), archived_at=None),
        SimpleNamespace(id=uuid.uuid4(), archived_at=None),
    ]

    class _DatasetQuery:
        def filter(self, *_args, **_kwargs):  # noqa: ANN001
            return self

        def first(self):  # noqa: ANN201
            return dataset_obj

    class _ExpiredQuery:
        def limit(self, _n):  # noqa: ANN001, ANN201
            return self

        def all(self):  # noqa: ANN201
            return expired_docs

    class _FakeDB(_DummyDB):
        def query(self, _model):  # noqa: ANN001, ANN201
            return _DatasetQuery()

    monkeypatch.setattr(rp, "_expired_documents_query", lambda *_a, **_k: _ExpiredQuery(), raising=True)
    monkeypatch.setattr(rp, "audit_log_event", lambda *_a, **_k: None, raising=True)

    summary = await rp.run_dataset_retention_sweep(
        _FakeDB(),
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        policy=DatasetRetentionPolicy(enabled=True, action="archive", max_age_days=30),
        dry_run=True,
        max_documents=10,
        max_versions_pruned=0,
        actor_id="system:retention",
        now=now,
    )

    assert summary["ok"] is True
    assert summary["dry_run"] is True
    assert summary["documents"]["eligible"] == 2
    assert summary["documents"]["archived"] == 0
    assert summary["documents"]["deleted"] == 0
    assert summary["policy"]["action"] == "archive"
    assert summary["policy"]["max_age_days"] == 30
    assert summary["cutoffs"]["created_at_lte"] is not None


@pytest.mark.asyncio
async def test_run_dataset_retention_sweep_delete_uses_system_membership_bypass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.schemas.dataset import DatasetRetentionPolicy
    from app.services import retention_jobs
    from app.services import retention_policy as rp

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    now = datetime.now(UTC)
    dataset_obj = SimpleNamespace(id=dataset_id, tenant_id=tenant_id, dataset_metadata={})
    expired_doc = SimpleNamespace(id=uuid.uuid4(), archived_at=None)
    delete_calls: list[dict[str, object]] = []

    class _ExpiredQuery:
        def limit(self, _n):  # noqa: ANN001, ANN201
            return self

        def all(self):  # noqa: ANN201
            return [expired_doc]

    async def _fake_delete_document_lifecycle(**kwargs):  # noqa: ANN003
        delete_calls.append(kwargs)

    monkeypatch.setattr(rp, "_expired_documents_query", lambda *_a, **_k: _ExpiredQuery(), raising=True)
    monkeypatch.setattr(retention_jobs, "_resolve_delete_document_lifecycle", lambda: _fake_delete_document_lifecycle, raising=True)
    monkeypatch.setattr(rp, "invalidate_dataset_cache_namespace", lambda *_a, **_k: "cache-token", raising=True)
    monkeypatch.setattr(rp, "audit_log_event", lambda *_a, **_k: None, raising=True)

    summary = await rp.run_dataset_retention_sweep(
        _CommitTrackingDB(dataset_obj=dataset_obj, tracked_docs=[expired_doc]),
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        policy=DatasetRetentionPolicy(enabled=True, action="delete", max_age_days=30),
        dry_run=False,
        max_documents=10,
        max_versions_pruned=0,
        actor_id="system:retention",
        now=now,
    )

    assert summary["documents"]["deleted"] == 1
    assert delete_calls == [
        {
            "document_id": expired_doc.id,
            "tenant_id": tenant_id,
            "account_id": "system:retention",
            "db": ANY,
            "enforce_permissions": False,
            "enforce_membership": False,
        }
    ]


@pytest.mark.asyncio
async def test_run_dataset_retention_sweep_archive_only_counts_after_successful_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api.schemas.dataset import DatasetRetentionPolicy
    from app.services import retention_policy as rp

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    now = datetime.now(UTC)
    dataset_obj = SimpleNamespace(id=dataset_id, tenant_id=tenant_id, dataset_metadata={})
    expired_doc = SimpleNamespace(id=uuid.uuid4(), archived_at=None)
    cache_invalidations: list[tuple[uuid.UUID, uuid.UUID]] = []

    class _ExpiredQuery:
        def limit(self, _n):  # noqa: ANN001, ANN201
            return self

        def all(self):  # noqa: ANN201
            return [expired_doc]

    def _invalidate_cache(_db, *, tenant_id, dataset_id):  # noqa: ANN001
        cache_invalidations.append((tenant_id, dataset_id))
        return "cache-token"

    monkeypatch.setattr(rp, "_expired_documents_query", lambda *_a, **_k: _ExpiredQuery(), raising=True)
    monkeypatch.setattr(rp, "invalidate_dataset_cache_namespace", _invalidate_cache, raising=True)
    monkeypatch.setattr(rp, "audit_log_event", lambda *_a, **_k: None, raising=True)

    summary = await rp.run_dataset_retention_sweep(
        _CommitTrackingDB(dataset_obj=dataset_obj, tracked_docs=[expired_doc], fail_commit_at=1),
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        policy=DatasetRetentionPolicy(enabled=True, action="archive", max_age_days=30),
        dry_run=False,
        max_documents=10,
        max_versions_pruned=0,
        actor_id="system:retention",
        now=now,
    )

    assert summary["documents"]["eligible"] == 1
    assert summary["documents"]["archived"] == 0
    assert summary["documents"]["errors"] == 1
    assert summary["cache_invalidation"] is None
    assert expired_doc.archived_at is None
    assert cache_invalidations == []
