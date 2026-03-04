from __future__ import annotations

import uuid
from datetime import datetime, timezone


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
    now = datetime(2026, 3, 4, 0, 0, 0, tzinfo=timezone.utc)

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
    now = datetime(2026, 3, 4, 0, 0, 0, tzinfo=timezone.utc)

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
    now = datetime(2026, 3, 4, 0, 0, 0, tzinfo=timezone.utc)

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

