from __future__ import annotations

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db


class _DummyDB:
    def commit(self) -> None:
        return None


def _override_get_db():  # noqa: ANN202
    yield _DummyDB()


def test_observability_perf_suite_run_endpoint_calls_service(monkeypatch):  # noqa: ANN001
    import app.api.v1.observability as obs_mod
    import app.services.perf_suite_run_service as perf_svc

    monkeypatch.setattr(obs_mod, "_ensure_admin", lambda *_args, **_kwargs: None, raising=True)

    assert hasattr(obs_mod, "run_perf_suite"), "Perf suite run endpoint not implemented yet"

    called: dict[str, object] = {}

    def _fake_run_minimal_perf_suite_report_and_diff(**kwargs):  # noqa: ANN202
        called.update(kwargs)
        return {
            "schema": "mimirq.perf_suite_run.v1",
            "baseline_path": "ci/perf_suite_baseline.v1.json",
            "policy_path": "ci/perf_regression_policy.v1.json",
            "baseline_ts": "2026-03-19T00:00:00Z",
            "current_report": {"ts": "2026-03-19T00:00:01Z", "suite": "perf-v1", "cases": []},
            "diff": {
                "schema": "mimirq.perf_suite_diff.v1",
                "strict_gate": {"passed": True, "regressions": 0},
                "cases": {},
            },
        }

    monkeypatch.setattr(
        perf_svc,
        "run_minimal_perf_suite_report_and_diff",
        _fake_run_minimal_perf_suite_report_and_diff,
        raising=True,
    )

    tenant_id = uuid.uuid4()

    def _override_get_tenant_id() -> uuid.UUID:
        return tenant_id

    def _override_get_current_account_id() -> str:
        return "test-account"

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id

    from app.api.v1.observability import run_perf_suite

    app.post("/api/v1/observability/perf-suite/run")(run_perf_suite)
    client = TestClient(app)

    res = client.post("/api/v1/observability/perf-suite/run", json={"iterations": 12, "timeout_sec": 1.5})
    assert res.status_code == 200, res.text
    body = res.json()

    assert body["schema"] == "mimirq.perf_suite_run.v1"
    assert called.get("iterations") == 12
    assert abs(float(called.get("timeout_sec") or 0.0) - 1.5) < 1e-6

