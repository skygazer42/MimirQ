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


def test_run_daily_stale_report_dry_run(monkeypatch):  # noqa: ANN001
    from app.services import stale_report_jobs

    db = _FakeDB()
    tenant_id = uuid.uuid4()
    now = datetime(2026, 3, 4, 0, 0, 0, tzinfo=UTC)

    doc1 = uuid.uuid4()
    doc2 = uuid.uuid4()

    rows = [
        {
            "connector_id": "github_repo",
            "run_dataset_id": uuid.uuid4(),
            "document_id": doc1,
            "linked_at": now,
            "document_dataset_id": uuid.uuid4(),
            "status": "completed",
            "created_at": now,
            "updated_at": now,
            "processed_at": now,
            "doc_metadata": {
                "source_last_modified_at": "2025-01-01T00:00:00Z",
                "source_last_modified_source": "http:last-modified",
                "source_fetched_at": "2026-03-01T00:00:00Z",
            },
        },
        {
            "connector_id": "url_batch",
            "run_dataset_id": uuid.uuid4(),
            "document_id": doc2,
            "linked_at": now,
            "document_dataset_id": uuid.uuid4(),
            "status": "completed",
            "created_at": now,
            "updated_at": now,
            "processed_at": now,
            "doc_metadata": {
                "source_last_modified_at": "2026-03-03T00:00:00Z",
                "source_last_modified_source": "http:last-modified",
                "source_fetched_at": "2026-03-03T00:00:00Z",
            },
        },
    ]

    monkeypatch.setattr(stale_report_jobs, "_list_connector_document_rows", lambda *_a, **_k: list(rows), raising=True)

    called = {"audit": 0}

    def _audit(_db, **kwargs):  # noqa: ANN001
        called["audit"] += 1

    monkeypatch.setattr(stale_report_jobs, "audit_log_event", _audit, raising=True)

    out = stale_report_jobs.run_daily_stale_report(
        db,
        tenant_id=tenant_id,
        stale_after_days=30,
        max_documents=5000,
        execute=False,
        now=now,
    )

    assert out.get("ok") is True
    assert out.get("dry_run") is True
    assert out.get("scanned") == 2
    assert out.get("stale") == 1
    assert called["audit"] == 0
    assert db.commits == 0


def test_run_daily_stale_report_execute_writes_audit(monkeypatch):  # noqa: ANN001
    from app.services import stale_report_jobs

    db = _FakeDB()
    tenant_id = uuid.uuid4()
    now = datetime(2026, 3, 4, 0, 0, 0, tzinfo=UTC)

    doc1 = uuid.uuid4()
    dataset1 = uuid.uuid4()

    rows = [
        {
            "connector_id": "github_repo",
            "run_dataset_id": dataset1,
            "document_id": doc1,
            "linked_at": now,
            "document_dataset_id": dataset1,
            "status": "completed",
            "created_at": now,
            "updated_at": now,
            "processed_at": now,
            "doc_metadata": {
                "source_last_modified_at": "2025-01-01T00:00:00Z",
                "source_last_modified_source": "http:last-modified",
                "source_fetched_at": "2026-03-01T00:00:00Z",
            },
        }
    ]

    monkeypatch.setattr(stale_report_jobs, "_audit_already_written", lambda *_a, **_k: False, raising=True)
    monkeypatch.setattr(stale_report_jobs, "_list_connector_document_rows", lambda *_a, **_k: list(rows), raising=True)

    called = {"audit": 0}

    def _audit(_db, **kwargs):  # noqa: ANN001
        called["audit"] += 1
        assert kwargs.get("action") == "connectors.stale_report.daily"
        assert kwargs.get("resource_type") == "stale_report"
        assert kwargs.get("resource_id") == "2026-03-04"
        details = kwargs.get("details") or {}
        assert details.get("scanned") == 1
        assert details.get("stale") == 1
        # PII-safe: no raw URL/content should be included.
        assert "source_url" not in details

    monkeypatch.setattr(stale_report_jobs, "audit_log_event", _audit, raising=True)

    out = stale_report_jobs.run_daily_stale_report(
        db,
        tenant_id=tenant_id,
        stale_after_days=30,
        max_documents=5000,
        execute=True,
        force=True,
        now=now,
    )

    assert out.get("ok") is True
    assert out.get("dry_run") is False
    assert called["audit"] == 1
    assert db.commits == 1

