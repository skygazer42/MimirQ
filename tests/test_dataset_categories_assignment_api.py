from __future__ import annotations

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.v1 import router as v1_router
from app.core.database import get_db


class _DummyDB:
    pass


def _override_get_db():  # noqa: ANN202
    yield _DummyDB()


def _override_get_tenant_id() -> uuid.UUID:
    return uuid.UUID("00000000-0000-0000-0000-000000000001")


def _override_get_current_account_id() -> str:
    return "test-account"


def test_dataset_categories_assignment_endpoints_exist(monkeypatch):  # noqa: ANN001
    dataset_id = uuid.uuid4()
    cat1 = uuid.uuid4()
    cat2 = uuid.uuid4()

    import app.api.v1.datasets as datasets_module

    monkeypatch.setattr(
        datasets_module.DatasetCategoryService,
        "list_dataset_category_ids",
        lambda *_a, **_k: [cat1],
        raising=True,
    )
    monkeypatch.setattr(
        datasets_module.DatasetCategoryService,
        "set_dataset_categories",
        lambda *_a, **_k: [cat1, cat2],
        raising=True,
    )

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.include_router(v1_router, prefix="/api/v1")
    client = TestClient(app)

    res = client.get(f"/api/v1/datasets/{dataset_id}/categories")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["dataset_id"] == str(dataset_id)
    assert body["category_ids"] == [str(cat1)]

    res2 = client.put(f"/api/v1/datasets/{dataset_id}/categories", json={"category_ids": [str(cat1), str(cat2)]})
    assert res2.status_code == 200, res2.text
    body2 = res2.json()
    assert body2["dataset_id"] == str(dataset_id)
    assert body2["category_ids"] == [str(cat1), str(cat2)]

