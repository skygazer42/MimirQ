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


def test_run_regression_run_retention_dry_run(monkeypatch):  # noqa: ANN001
    from app.services import retention_jobs

    db = _FakeDB()
    tenant_id = uuid.uuid4()
    now = datetime(2026, 2, 27, 0, 0, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(retention_jobs, "plan_regression_run_purge", lambda *_a, **_k: 12, raising=True)

    def _purge(*_a, **_k):  # noqa: ANN001
        raise AssertionError("purge_regression_run_rows must not run in dry_run mode")

    monkeypatch.setattr(retention_jobs, "purge_regression_run_rows", _purge, raising=True)

    def _audit(_db, **kwargs):  # noqa: ANN001
        assert kwargs.get("action") == "evaluations.regression_runs.retention"
        details = kwargs.get("details") or {}
        assert details.get("dry_run") is True
        assert details.get("eligible_runs") == 12
        assert details.get("deleted_runs") == 0
        assert details.get("deleted_items") == 0

    monkeypatch.setattr(retention_jobs, "audit_log_event", _audit, raising=True)

    out = retention_jobs.run_regression_run_retention(
        db,
        tenant_id=tenant_id,
        retention_days=90,
        max_delete=1000,
        dry_run=True,
        actor_id="system:test",
        now=now,
    )

    assert out.get("eligible_runs") == 12
    assert out.get("deleted_runs") == 0
    assert out.get("deleted_items") == 0
    assert db.commits == 1


def test_run_regression_run_retention_execute(monkeypatch):  # noqa: ANN001
    from app.services import retention_jobs

    db = _FakeDB()
    tenant_id = uuid.uuid4()
    now = datetime(2026, 2, 27, 0, 0, 0, tzinfo=timezone.utc)

    monkeypatch.setattr(retention_jobs, "plan_regression_run_purge", lambda *_a, **_k: 3, raising=True)
    monkeypatch.setattr(retention_jobs, "purge_regression_run_rows", lambda *_a, **_k: (2, 15), raising=True)

    def _audit(_db, **kwargs):  # noqa: ANN001
        details = kwargs.get("details") or {}
        assert details.get("dry_run") is False
        assert details.get("eligible_runs") == 3
        assert details.get("deleted_runs") == 2
        assert details.get("deleted_items") == 15

    monkeypatch.setattr(retention_jobs, "audit_log_event", _audit, raising=True)

    out = retention_jobs.run_regression_run_retention(
        db,
        tenant_id=tenant_id,
        retention_days=30,
        max_delete=500,
        dry_run=False,
        actor_id="system:test",
        now=now,
    )

    assert out.get("eligible_runs") == 3
    assert out.get("deleted_runs") == 2
    assert out.get("deleted_items") == 15
    assert db.commits == 1

