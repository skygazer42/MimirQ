from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db


class _DummyDB: ...


def _override_get_db():  # noqa: ANN202
    yield _DummyDB()


def test_observability_periodic_job_freshness_endpoint(monkeypatch):  # noqa: ANN001
    import app.api.v1.observability as obs_mod

    # Bypass role checks.
    monkeypatch.setattr(obs_mod, "_ensure_admin", lambda *args, **kwargs: None, raising=True)

    tenant_id = uuid.uuid4()
    now = datetime(2026, 3, 5, 0, 0, 0, tzinfo=timezone.utc)

    expected = {
        "schema": "mimirq.periodic_job_freshness.v1",
        "generated_at": now,
        "tenant_id": str(tenant_id),
        "items": [
            {
                "key": "access_review_daily",
                "action": "compliance.access_review.daily",
                "resource_type": "access_review_summary",
                "expected_interval_hours": 24,
                "stale_after_hours": 36,
                "last_created_at": now,
                "last_resource_id": "2026-03-05",
                "age_seconds": 0,
                "stale": False,
            }
        ],
    }

    monkeypatch.setattr(obs_mod, "build_periodic_job_freshness_snapshot", lambda *_args, **_kwargs: expected, raising=True)

    def _override_get_tenant_id() -> uuid.UUID:
        return tenant_id

    def _override_get_current_account_id() -> str:
        return "test-account"

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id

    from app.api.v1.observability import get_periodic_job_freshness

    app.get("/api/v1/observability/periodic-jobs/freshness")(get_periodic_job_freshness)
    client = TestClient(app)

    res = client.get("/api/v1/observability/periodic-jobs/freshness")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["schema"] == "mimirq.periodic_job_freshness.v1"
    assert body["tenant_id"] == str(tenant_id)
    assert len(body.get("items") or []) == 1

