from __future__ import annotations

import uuid

import pytest


class _FakeDB:
    def __init__(self) -> None:
        self.closed = 0

    def close(self) -> None:
        self.closed += 1

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None


@pytest.mark.asyncio
async def test_evidence_reference_sources_repair_job_success(monkeypatch):
    import app.tasks.jobs as jobs_mod

    tenant_id = uuid.uuid4()
    suite_id = uuid.uuid4()

    fake_db = _FakeDB()
    monkeypatch.setattr(jobs_mod, "SessionLocal", lambda: fake_db, raising=True)

    expected = {
        "suite_id": str(suite_id),
        "dataset_id": str(uuid.uuid4()),
        "applied": True,
        "scanned_items": 1,
        "scanned_references": 2,
        "drifted_references": 1,
        "repaired_references": 1,
        "skipped_approved_items": 0,
        "skipped_archived_items": 0,
        "changes_truncated": False,
        "changes": [],
    }

    def _fake_repair(*_a, **_k):  # noqa: ANN001, ANN202
        return dict(expected)

    monkeypatch.setattr(jobs_mod, "repair_evidence_suite_reference_sources", _fake_repair, raising=True)
    monkeypatch.setattr(jobs_mod, "audit_log_event", lambda *_a, **_k: None, raising=True)

    out = await jobs_mod.evidence_reference_sources_repair_job(
        {"redis": None},
        str(tenant_id),
        str(suite_id),
        "system:test",
        True,
        False,
        False,
        100,
        50,
        500,
    )

    assert out.get("ok") is True
    assert out.get("result") == expected
    assert fake_db.closed == 1


@pytest.mark.asyncio
async def test_evidence_reference_sources_repair_job_raises_for_retry(monkeypatch):
    import app.tasks.jobs as jobs_mod

    fake_db = _FakeDB()
    monkeypatch.setattr(jobs_mod, "SessionLocal", lambda: fake_db, raising=True)

    def _boom(*_a, **_k):  # noqa: ANN001, ANN202
        raise RuntimeError("boom")

    monkeypatch.setattr(jobs_mod, "repair_evidence_suite_reference_sources", _boom, raising=True)

    with pytest.raises(RuntimeError):
        await jobs_mod.evidence_reference_sources_repair_job(
            {"redis": None},
            str(uuid.uuid4()),
            str(uuid.uuid4()),
            "system:test",
            True,
            False,
            False,
            100,
            50,
            500,
        )

