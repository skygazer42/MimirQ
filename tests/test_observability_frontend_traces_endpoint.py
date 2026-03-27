from uuid import UUID

from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_observability_frontend_traces_endpoint_logs_trace(monkeypatch):  # noqa: ANN001
    import app.api.v1.observability as obs_mod
    from app.api.v1.observability import report_frontend_trace

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
    app.post("/api/v1/observability/frontend-traces", status_code=202)(report_frontend_trace)

    client = TestClient(app)
    res = client.post(
        "/api/v1/observability/frontend-traces",
        json={
            "event": "graph_render_projection",
            "duration_ms": 18.4,
            "component": "graph-display-filters",
            "page": "/graph",
            "input_node_count": 128,
            "input_link_count": 256,
            "output_node_count": 42,
            "output_link_count": 84,
            "active_filter_count": 2,
        },
        headers={"user-agent": "vitest-agent"},
    )

    assert res.status_code == 202
    assert captured
    payload = captured[0]
    assert payload["event"] == "frontend_trace"
    assert payload["trace_event"] == "graph_render_projection"
    assert payload["duration_ms"] == 18.4
    assert payload["component"] == "graph-display-filters"
    assert payload["page"] == "/graph"
    assert payload["tenant_id"] == str(tenant_id)
    assert payload["account_id"] == "acct-1"
    assert payload["input_node_count"] == 128
    assert payload["output_node_count"] == 42
