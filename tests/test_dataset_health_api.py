from __future__ import annotations

import uuid
from datetime import UTC, datetime

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
    return uuid.uuid4()


def _override_get_current_account_id() -> str:
    return "test-account"


def test_dataset_health_summary(monkeypatch):  # noqa: ANN001
    import app.api.v1.datasets as datasets_module
    from app.api.schemas.dataset_profile import DatasetProfileSummary

    dataset_id = uuid.uuid4()

    dummy_summary = DatasetProfileSummary(
        dataset_id=dataset_id,
        generated_at=datetime(2026, 1, 1, tzinfo=UTC),
        total_documents=3,
        by_status={"completed": 2, "failed": 1},
    )

    monkeypatch.setattr(
        datasets_module,
        "compute_dataset_profile_summary",
        lambda *_a, **_k: dummy_summary,
        raising=True,
    )

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.include_router(datasets_module.router, prefix="/api/v1/datasets")
    client = TestClient(app)

    res = client.get(f"/api/v1/datasets/{dataset_id}/health")
    assert res.status_code == 200, res.text
    body = res.json()
    assert "profile" in body
    assert "ingestion" in body

