from __future__ import annotations


def test_purge_regression_runs_endpoint_is_registered_and_admin_only():
    # Avoid importing app.api.v1.evaluations (it pulls in heavy ML deps).
    from pathlib import Path

    text = Path("app/api/v1/evaluations.py").read_text(encoding="utf-8")
    assert '@router.post("/ragas/regression/runs/purge")' in text
    assert "TenantPermissions.LIFECYCLE_MANAGE" in text

