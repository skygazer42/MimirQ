from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.mark.parametrize("metric_name", ["LCP", "CLS"])
def test_observability_frontend_vitals_endpoint_logs_metric(monkeypatch, metric_name):  # noqa: ANN001
    import app.api.v1.observability as obs_mod
    from app.api.v1.observability import report_frontend_web_vital

    captured = []

    monkeypatch.setattr(
        obs_mod,
        "log_metrics",
        lambda payload: captured.append(dict(payload)),
        raising=True,
    )
    monkeypatch.setattr(
        obs_mod.DatasetService,
        "ensure_member",
        lambda _db, _tenant_id, _account_id: None,
        raising=True,
    )

    app = FastAPI()
    tenant_id = UUID("00000000-0000-0000-0000-000000000001")

    app.dependency_overrides[obs_mod.get_db] = lambda: object()
    app.dependency_overrides[obs_mod.get_tenant_id] = lambda: tenant_id
    app.dependency_overrides[obs_mod.get_current_account_id] = lambda: "acct-1"
    app.post("/api/v1/observability/frontend-vitals", status_code=202)(report_frontend_web_vital)

    client = TestClient(app)
    res = client.post(
        "/api/v1/observability/frontend-vitals",
        json={
            "name": metric_name,
            "value": 1820.4,
            "rating": "good",
            "id": "metric-1",
            "navigation_type": "navigate",
            "page": "/chat",
        },
        headers={"user-agent": "vitest-agent"},
    )

    assert res.status_code == 202
    assert captured
    payload = captured[0]
    assert payload["event"] == "frontend_web_vital"
    assert payload["metric_name"] == metric_name
    assert payload["metric_value"] == 1820.4
    assert payload["tenant_id"] == str(tenant_id)
    assert payload["account_id"] == "acct-1"
    assert payload["page"] == "/chat"
