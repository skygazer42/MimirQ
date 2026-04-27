from __future__ import annotations

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db


class _DummyDB:
    pass


def _override_get_db():  # noqa: ANN202
    yield _DummyDB()


def _override_get_tenant_id() -> uuid.UUID:
    return uuid.UUID("00000000-0000-0000-0000-000000000001")


def _override_get_current_account_id() -> str:
    return "test-account"


def test_dataset_analysis_dashboard_endpoint_returns_tenant_summary(monkeypatch):  # noqa: ANN001
    captured: dict[str, object] = {}

    import app.api.v1.dataset_analysis as module

    monkeypatch.setattr(module.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)

    def _fake_dashboard(**kwargs):  # noqa: ANN003
        captured.update(kwargs)
        return {
            "schema": "mimirq.dataset_analysis.dashboard.v1",
            "tenant_id": str(kwargs["tenant_id"]),
            "dataset_count": 2,
            "summary": {"all_interactions": 18, "feedback_interactions": 5},
            "datasets": [{"dataset_id": "ds-1", "dataset_name": "Dataset A"}],
        }

    monkeypatch.setattr(module, "build_tenant_dataset_analysis_dashboard", _fake_dashboard, raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.include_router(module.router, prefix="/api/v1/datasets")
    client = TestClient(app)

    res = client.get("/api/v1/datasets/analysis/dashboard", params={"limit": 7, "feedback_polarity": "negative"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["schema"] == "mimirq.dataset_analysis.dashboard.v1"
    assert body["dataset_count"] == 2
    assert body["summary"]["all_interactions"] == 18
    assert captured["limit"] == 7
    assert captured["feedback_polarity"] == "negative"
