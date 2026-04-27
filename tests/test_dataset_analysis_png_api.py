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


def test_dataset_analysis_png_task_endpoints_exist(monkeypatch):  # noqa: ANN001
    dataset_id = uuid.uuid4()
    task_id = "task-1"

    import app.api.v1.dataset_analysis as module

    class _Dataset:
        id = dataset_id
        name = "Dataset PNG"

    monkeypatch.setattr(module.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(module.DatasetService, "get_dataset", lambda *_a, **_k: _Dataset(), raising=True)
    monkeypatch.setattr(
        module,
        "create_dataset_analysis_png_task",
        lambda **_kwargs: {"task_id": task_id, "status": "pending"},
        raising=True,
    )
    monkeypatch.setattr(
        module,
        "get_dataset_analysis_png_task_status",
        lambda **_kwargs: {"task_id": task_id, "status": "done"},
        raising=True,
    )
    monkeypatch.setattr(
        module,
        "get_dataset_analysis_png_result",
        lambda **_kwargs: b"\x89PNG\r\n\x1a\npayload",
        raising=True,
    )

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.include_router(module.router, prefix="/api/v1/datasets")
    client = TestClient(app)

    res = client.post(f"/api/v1/datasets/{dataset_id}/analysis/export.png")
    assert res.status_code == 202, res.text
    assert res.json()["task_id"] == task_id

    res2 = client.get(f"/api/v1/datasets/{dataset_id}/analysis/export-tasks/{task_id}")
    assert res2.status_code == 200, res2.text
    assert res2.json()["status"] == "done"

    res3 = client.get(f"/api/v1/datasets/{dataset_id}/analysis/export-tasks/{task_id}/result.png")
    assert res3.status_code == 200, res3.text
    assert res3.content.startswith(b"\x89PNG\r\n\x1a\n")
    assert "image/png" in res3.headers["content-type"]
