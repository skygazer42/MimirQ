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


def test_dataset_analysis_export_json_endpoint_returns_aggregate_payload(monkeypatch):  # noqa: ANN001
    dataset_id = uuid.uuid4()

    import app.api.v1.dataset_analysis as module

    class _Dataset:
        id = dataset_id
        name = "Dataset Export"

    monkeypatch.setattr(module.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(module.DatasetService, "get_dataset", lambda *_a, **_k: _Dataset(), raising=True)
    monkeypatch.setattr(
        module,
        "export_dataset_analysis_json",
        lambda **kwargs: {
            "meta": {"filters": {"dataset_id": str(kwargs["dataset_id"])}, "schema_version": "mimirq.dataset_analysis.export.v1"},
            "metrics": {"raw_positive_rate": 0.7},
        },
        raising=True,
    )

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.include_router(module.router, prefix="/api/v1/datasets")
    client = TestClient(app)

    res = client.get(f"/api/v1/datasets/{dataset_id}/analysis/export.json")
    assert res.status_code == 200, res.text
    assert res.json()["meta"]["filters"]["dataset_id"] == str(dataset_id)


def test_dataset_analysis_export_jsonl_endpoint_returns_ndjson(monkeypatch):  # noqa: ANN001
    dataset_id = uuid.uuid4()

    import app.api.v1.dataset_analysis as module

    class _Dataset:
        id = dataset_id
        name = "Dataset Export"

    monkeypatch.setattr(module.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(module.DatasetService, "get_dataset", lambda *_a, **_k: _Dataset(), raising=True)
    monkeypatch.setattr(
        module,
        "export_dataset_analysis_jsonl",
        lambda **_kwargs: '{"interaction_id":"req-1"}\n{"interaction_id":"req-2"}\n',
        raising=True,
    )

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.include_router(module.router, prefix="/api/v1/datasets")
    client = TestClient(app)

    res = client.get(f"/api/v1/datasets/{dataset_id}/analysis/export.jsonl")
    assert res.status_code == 200, res.text
    assert "application/x-ndjson" in res.headers["content-type"]
    assert '{"interaction_id":"req-1"}' in res.text
