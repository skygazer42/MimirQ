from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone


def test_periodic_job_freshness_service_marks_missing_as_stale(monkeypatch):  # noqa: ANN001
    import app.services.periodic_job_freshness_service as svc

    tenant_id = uuid.uuid4()
    now = datetime(2026, 3, 5, 0, 0, 0, tzinfo=timezone.utc)

    def _fake_latest_event(*_args, **_kwargs):  # noqa: ANN202
        return None

    monkeypatch.setattr(svc, "_latest_audit_event", _fake_latest_event, raising=True)

    snap = svc.build_periodic_job_freshness_snapshot(db=None, tenant_id=tenant_id, now=now)
    assert snap["schema"] == "mimirq.periodic_job_freshness.v1"
    assert snap["tenant_id"] == str(tenant_id)
    assert snap["generated_at"] == now

    items = snap.get("items") or []
    assert len(items) >= 1
    assert all(bool(it.get("stale")) for it in items)


def test_periodic_job_freshness_service_marks_recent_as_not_stale(monkeypatch):  # noqa: ANN001
    import app.services.periodic_job_freshness_service as svc

    tenant_id = uuid.uuid4()
    now = datetime(2026, 3, 5, 0, 0, 0, tzinfo=timezone.utc)
    recent = now - timedelta(hours=2)

    def _fake_latest_event(*_args, **_kwargs):  # noqa: ANN202
        return {
            "created_at": recent,
            "resource_id": "2026-03-04",
        }

    monkeypatch.setattr(svc, "_latest_audit_event", _fake_latest_event, raising=True)

    snap = svc.build_periodic_job_freshness_snapshot(db=None, tenant_id=tenant_id, now=now)
    items = snap.get("items") or []
    assert len(items) >= 1
    assert any(it.get("last_created_at") == recent and (not it.get("stale")) for it in items)

