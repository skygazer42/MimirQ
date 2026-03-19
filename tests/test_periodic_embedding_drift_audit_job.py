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


def test_run_daily_embedding_drift_report_execute_writes_audit(monkeypatch):  # noqa: ANN001
    from app.services import periodic_audit_jobs

    assert hasattr(periodic_audit_jobs, "run_daily_embedding_drift_report"), "Embedding drift periodic job not implemented yet"

    db = _FakeDB()
    tenant_id = uuid.uuid4()
    now = datetime(2026, 3, 4, 0, 0, 0, tzinfo=UTC)

    monkeypatch.setattr(periodic_audit_jobs, "_audit_already_written", lambda *_a, **_k: False, raising=True)

    def _fake_run_embedding_drift_monitor(**kwargs):  # noqa: ANN202
        assert kwargs.get("tenant_id") == tenant_id
        return {
            "schema": "mimirq.embedding_drift_snapshot.v1",
            "ok": True,
            "sample_n_used": int(kwargs.get("sample_n") or 0),
            "threshold": float(kwargs.get("drift_threshold") or 0.0),
            "missing_vectors": 0,
            "dim_mismatch": 0,
            "sampled_items": 10,
            "drift": {"count": 10, "avg": 0.01, "p95": 0.02, "p99": 0.03, "max": 0.04, "min": 0.0},
            "above_threshold": {"count": 0, "ratio": 0.0},
        }

    monkeypatch.setattr(periodic_audit_jobs, "run_embedding_drift_monitor", _fake_run_embedding_drift_monitor, raising=True)

    called = {"audit": 0}

    def _audit(_db, **kwargs):  # noqa: ANN001
        called["audit"] += 1
        assert kwargs.get("action") == "observability.embedding_drift.daily"
        assert kwargs.get("resource_type") == "embedding_drift_report"
        assert kwargs.get("resource_id") == "2026-03-04"
        details = kwargs.get("details") or {}
        assert details.get("sample_n_used") == 12
        assert abs(float(details.get("threshold") or 0.0) - 0.2) < 1e-6
        # PII-safe: no raw chunk content or ids.
        assert "content" not in details
        assert "vector_id" not in details
        assert "document_id" not in details

    monkeypatch.setattr(periodic_audit_jobs, "audit_log_event", _audit, raising=True)

    out = periodic_audit_jobs.run_daily_embedding_drift_report(
        db,
        tenant_id=tenant_id,
        execute=True,
        force=True,
        sample_n=12,
        drift_threshold=0.2,
        now=now,
    )

    assert out.get("ok") is True
    assert out.get("dry_run") is False
    assert called["audit"] == 1
    assert db.commits == 1

