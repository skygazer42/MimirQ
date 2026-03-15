from __future__ import annotations

import uuid
from datetime import UTC, datetime


class _FakeDB:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    def commit(self) -> None:  # noqa: D401
        self.commits += 1

    def rollback(self) -> None:  # noqa: D401
        self.rollbacks += 1


def test_run_daily_index_audit_report_dry_run_is_bounded(monkeypatch):  # noqa: ANN001
    from app.services import periodic_audit_jobs

    db = _FakeDB()
    tenant_id = uuid.uuid4()
    now = datetime(2026, 3, 4, 0, 0, 0, tzinfo=UTC)

    dataset_ids = [uuid.uuid4(), uuid.uuid4(), uuid.uuid4()]
    monkeypatch.setattr(
        periodic_audit_jobs,
        "_list_dataset_ids_for_index_audit",
        lambda *_a, **_k: list(dataset_ids),
        raising=True,
    )

    called: list[uuid.UUID] = []

    def _fake_index_audit(*_a, **kwargs):  # noqa: ANN001, ANN202
        called.append(kwargs["dataset_id"])
        return {
            "tenant_id": str(kwargs["tenant_id"]),
            "dataset_id": str(kwargs["dataset_id"]),
            "vector_backend": "milvus",
            "active_documents": 1,
            "active_chunks": 2,
            "vector_id_missing": 0,
            "vector_ids_checked": 2,
            "vector_ids_missing_in_backend": 1,
            "vector_ids_missing_in_backend_sample": ["deadbeef"],
            "milvus_ids_sampled": 0,
            "milvus_orphan_ids_sample": [],
        }

    monkeypatch.setattr(periodic_audit_jobs, "run_dataset_index_audit_internal", _fake_index_audit, raising=True)

    monkeypatch.setattr(
        periodic_audit_jobs,
        "audit_log_event",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("dry-run must not write audit logs")),
        raising=True,
    )

    out = periodic_audit_jobs.run_daily_index_audit_report(
        db,
        tenant_id=tenant_id,
        max_datasets=2,
        execute=False,
        now=now,
    )

    assert out.get("ok") is True
    assert out.get("dry_run") is True
    assert out.get("scanned_datasets") == 2
    assert len(called) == 2
    assert db.commits == 0


def test_run_daily_evidence_drift_audit_execute_writes_audit(monkeypatch):  # noqa: ANN001
    from app.services import periodic_audit_jobs

    db = _FakeDB()
    tenant_id = uuid.uuid4()
    now = datetime(2026, 3, 4, 0, 0, 0, tzinfo=UTC)

    dataset_id = uuid.uuid4()

    monkeypatch.setattr(periodic_audit_jobs, "_audit_already_written", lambda *_a, **_k: False, raising=True)
    monkeypatch.setattr(
        periodic_audit_jobs,
        "_list_dataset_ids_for_drift_audit",
        lambda *_a, **_k: [dataset_id],
        raising=True,
    )

    def _fake_dataset_drift_audit(*_a, **kwargs):  # noqa: ANN001, ANN202
        assert kwargs.get("dataset_id") == dataset_id
        return {
            "dataset_id": str(dataset_id),
            "total_items": 3,
            "total_references": 10,
            "ok_references": 8,
            "drift_references": 2,
            "drift_rate": 0.2,
            "reasons": {"chunk_missing": 2},
            "details_truncated": False,
        }

    monkeypatch.setattr(periodic_audit_jobs, "_run_dataset_evidence_drift_audit", _fake_dataset_drift_audit, raising=True)

    called = {"audit": 0}

    def _audit(_db, **kwargs):  # noqa: ANN001
        called["audit"] += 1
        assert kwargs.get("action") == "evidence.drift_audit.daily"
        assert kwargs.get("resource_type") == "evidence_drift_report"
        assert kwargs.get("resource_id") == "2026-03-04"
        details = kwargs.get("details") or {}
        assert details.get("scanned_datasets") == 1
        assert details.get("drift_references") == 2
        # PII-safe: no raw evidence item fields should be present.
        assert "query" not in details
        assert "expected_answer" not in details
        assert "reference_sources" not in details

    monkeypatch.setattr(periodic_audit_jobs, "audit_log_event", _audit, raising=True)

    out = periodic_audit_jobs.run_daily_evidence_drift_audit_report(
        db,
        tenant_id=tenant_id,
        max_datasets=10,
        execute=True,
        force=True,
        now=now,
    )

    assert out.get("ok") is True
    assert out.get("dry_run") is False
    assert called["audit"] == 1
    assert db.commits == 1


def test_run_daily_index_audit_report_execute_dedupes(monkeypatch):  # noqa: ANN001
    from app.services import periodic_audit_jobs

    db = _FakeDB()
    tenant_id = uuid.uuid4()
    now = datetime(2026, 3, 4, 0, 0, 0, tzinfo=UTC)

    monkeypatch.setattr(periodic_audit_jobs, "_audit_already_written", lambda *_a, **_k: True, raising=True)

    out = periodic_audit_jobs.run_daily_index_audit_report(
        db,
        tenant_id=tenant_id,
        max_datasets=10,
        execute=True,
        force=False,
        now=now,
    )

    assert out.get("ok") is True
    assert out.get("skipped") is True
    assert out.get("skip_reason") == "already_written"
    assert db.commits == 0


class _FakeCountQuery:
    def __init__(self, *, model, counts):  # noqa: ANN001
        self._model = model
        self._counts = counts
        self._filters: dict[str, object] = {}
        self._has_or = False

    def filter(self, *conds, **_kwargs):  # noqa: ANN001
        for expr in conds:
            left_key = getattr(getattr(expr, "left", None), "key", None)
            right_val = getattr(getattr(expr, "right", None), "value", None)
            if left_key:
                self._filters[str(left_key)] = right_val
                continue
            if hasattr(expr, "clauses"):
                # Best-effort: mark OR expressions used by inherit-mode queries.
                self._has_or = True
        return self

    def count(self) -> int:
        key = (self._model, tuple(sorted(self._filters.items())), bool(self._has_or))
        if key in self._counts:
            return int(self._counts[key] or 0)
        key2 = (self._model, tuple(sorted(self._filters.items())))
        if key2 in self._counts:
            return int(self._counts[key2] or 0)
        if self._model in self._counts:
            return int(self._counts[self._model] or 0)
        return 0


class _FakeCountDB(_FakeDB):
    def __init__(self, *, counts):  # noqa: ANN001
        super().__init__()
        self._counts = counts

    def query(self, model):  # noqa: ANN001
        return _FakeCountQuery(model=model, counts=self._counts)


def test_run_daily_access_review_summary_dry_run_is_pii_safe_and_bounded(monkeypatch):  # noqa: ANN001
    from app.services import periodic_audit_jobs

    tenant_id = uuid.uuid4()
    now = datetime(2026, 3, 4, 0, 0, 0, tzinfo=UTC)

    counts = {
        (periodic_audit_jobs.TenantGroup, (("tenant_id", tenant_id),), False): 3,
        (periodic_audit_jobs.TenantGroupMember, (("tenant_id", tenant_id),), False): 9,
        (periodic_audit_jobs.Dataset, (("tenant_id", tenant_id),), False): 8,
        (periodic_audit_jobs.Dataset, (("permission", periodic_audit_jobs.DatasetPermissionEnum.ALL_TEAM_MEMBERS), ("tenant_id", tenant_id)), False): 6,
        (periodic_audit_jobs.Dataset, (("permission", periodic_audit_jobs.DatasetPermissionEnum.ONLY_ME), ("tenant_id", tenant_id)), False): 1,
        (periodic_audit_jobs.Dataset, (("permission", periodic_audit_jobs.DatasetPermissionEnum.PARTIAL_MEMBERS), ("tenant_id", tenant_id)), False): 1,
        (periodic_audit_jobs.DatasetPermission, (("tenant_id", tenant_id),), False): 11,
        (periodic_audit_jobs.DatasetGroupPermission, (("tenant_id", tenant_id),), False): 5,
        (periodic_audit_jobs.Document, (("tenant_id", tenant_id),), False): 10,
        (periodic_audit_jobs.Document, (("tenant_id", tenant_id),), True): 2,  # inherit-mode OR clause
        (periodic_audit_jobs.Document, (("access_mode", "partial_members"), ("tenant_id", tenant_id)), False): 3,
        (periodic_audit_jobs.Document, (("access_mode", "only_me"), ("tenant_id", tenant_id)), False): 1,
        (periodic_audit_jobs.Document, (("access_mode", "all_team_members"), ("tenant_id", tenant_id)), False): 4,
        (periodic_audit_jobs.DocumentPermission, (("tenant_id", tenant_id),), False): 21,
        (periodic_audit_jobs.DocumentGroupPermission, (("tenant_id", tenant_id),), False): 7,
    }

    db = _FakeCountDB(counts=counts)

    monkeypatch.setattr(
        periodic_audit_jobs,
        "audit_log_event",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("dry-run must not write audit logs")),
        raising=True,
    )

    out = periodic_audit_jobs.run_daily_access_review_summary(
        db,
        tenant_id=tenant_id,
        execute=False,
        force=False,
        now=now,
    )

    assert out.get("ok") is True
    assert out.get("dry_run") is True
    assert out.get("tenant_id") == str(tenant_id)
    assert out.get("report_date") == "2026-03-04"
    assert out.get("group_count") == 3
    assert out.get("group_member_count") == 9
    assert out.get("dataset_count") == 8
    assert out.get("dataset_member_allowlist_count") == 11
    assert out.get("dataset_group_allowlist_count") == 5
    assert out.get("document_count") == 10
    assert out.get("document_member_allowlist_count") == 21
    assert out.get("document_group_allowlist_count") == 7
    assert (out.get("document_access_mode_counts") or {}).get("unknown") == 0
    assert db.commits == 0


def test_run_daily_access_review_summary_execute_writes_audit(monkeypatch):  # noqa: ANN001
    from app.services import periodic_audit_jobs

    tenant_id = uuid.uuid4()
    now = datetime(2026, 3, 4, 0, 0, 0, tzinfo=UTC)

    counts = {
        (periodic_audit_jobs.TenantGroup, (("tenant_id", tenant_id),), False): 1,
        (periodic_audit_jobs.TenantGroupMember, (("tenant_id", tenant_id),), False): 2,
        (periodic_audit_jobs.Dataset, (("tenant_id", tenant_id),), False): 0,
        (periodic_audit_jobs.Dataset, (("permission", periodic_audit_jobs.DatasetPermissionEnum.ALL_TEAM_MEMBERS), ("tenant_id", tenant_id)), False): 0,
        (periodic_audit_jobs.Dataset, (("permission", periodic_audit_jobs.DatasetPermissionEnum.ONLY_ME), ("tenant_id", tenant_id)), False): 0,
        (periodic_audit_jobs.Dataset, (("permission", periodic_audit_jobs.DatasetPermissionEnum.PARTIAL_MEMBERS), ("tenant_id", tenant_id)), False): 0,
        (periodic_audit_jobs.DatasetPermission, (("tenant_id", tenant_id),), False): 0,
        (periodic_audit_jobs.DatasetGroupPermission, (("tenant_id", tenant_id),), False): 0,
        (periodic_audit_jobs.Document, (("tenant_id", tenant_id),), False): 0,
        (periodic_audit_jobs.Document, (("tenant_id", tenant_id),), True): 0,
        (periodic_audit_jobs.DocumentPermission, (("tenant_id", tenant_id),), False): 0,
        (periodic_audit_jobs.DocumentGroupPermission, (("tenant_id", tenant_id),), False): 0,
    }
    db = _FakeCountDB(counts=counts)

    monkeypatch.setattr(periodic_audit_jobs, "_audit_already_written", lambda *_a, **_k: False, raising=True)

    called = {"audit": 0}

    def _audit(_db, **kwargs):  # noqa: ANN001
        called["audit"] += 1
        assert kwargs.get("action") == "compliance.access_review.daily"
        assert kwargs.get("resource_type") == "access_review_summary"
        assert kwargs.get("resource_id") == "2026-03-04"
        details = kwargs.get("details") or {}
        assert details.get("schema") == "mimirq.access_review_daily.v1"
        assert details.get("report_date") == "2026-03-04"
        assert details.get("tenant_id") == str(tenant_id)
        assert "ok" not in details

    monkeypatch.setattr(periodic_audit_jobs, "audit_log_event", _audit, raising=True)

    out = periodic_audit_jobs.run_daily_access_review_summary(
        db,
        tenant_id=tenant_id,
        execute=True,
        force=True,
        now=now,
    )

    assert out.get("ok") is True
    assert out.get("dry_run") is False
    assert called["audit"] == 1
    assert db.commits == 1


def test_run_daily_access_review_summary_execute_dedupes(monkeypatch):  # noqa: ANN001
    from app.services import periodic_audit_jobs

    db = _FakeCountDB(counts={})
    tenant_id = uuid.uuid4()
    now = datetime(2026, 3, 4, 0, 0, 0, tzinfo=UTC)

    monkeypatch.setattr(periodic_audit_jobs, "_audit_already_written", lambda *_a, **_k: True, raising=True)

    out = periodic_audit_jobs.run_daily_access_review_summary(
        db,
        tenant_id=tenant_id,
        execute=True,
        force=False,
        now=now,
    )

    assert out.get("ok") is True
    assert out.get("skipped") is True
    assert out.get("skip_reason") == "already_written"
    assert db.commits == 0
