from __future__ import annotations

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db


def test_ingestion_policy_versioning_and_rollback(monkeypatch):  # noqa: ANN001
    import app.api.v1.datasets as datasets_module
    from app.services.dataset_service import DatasetService

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()

    class _DummyDataset:
        def __init__(self) -> None:
            self.id = dataset_id
            self.tenant_id = tenant_id
            self.name = "Demo"
            self.dataset_metadata = {}

    ds = _DummyDataset()

    monkeypatch.setattr(DatasetService, "get_dataset", lambda *_a, **_k: ds, raising=True)
    monkeypatch.setattr(DatasetService, "assert_dataset_readable", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(DatasetService, "assert_dataset_writable", lambda *_a, **_k: None, raising=True)

    class _DummyDB:
        def commit(self) -> None:
            return None

        def refresh(self, _obj) -> None:  # noqa: ANN001
            return None

    def _override_get_db():  # noqa: ANN202
        yield _DummyDB()

    def _override_get_tenant_id() -> uuid.UUID:
        return tenant_id

    def _override_get_current_account_id() -> str:
        return "test-account"

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.include_router(datasets_module.router, prefix="/api/v1/datasets")
    client = TestClient(app)

    policy_v1 = {"version": "1", "rules": [{"id": "r1", "name": "Rule 1", "enabled": True, "match": {"extensions": []}}]}
    res = client.put(f"/api/v1/datasets/{dataset_id}/ingestion-policy", json=policy_v1)
    assert res.status_code == 200, res.text

    versions = client.get(f"/api/v1/datasets/{dataset_id}/ingestion-policy/versions")
    assert versions.status_code == 200, versions.text
    body = versions.json()
    assert body.get("current_version_id")
    assert isinstance(body.get("items"), list) and len(body["items"]) >= 1
    first_version_id = body["items"][0]["id"]

    policy_v2 = {
        "version": "1",
        "rules": [
            {"id": "r1", "name": "Rule 1", "enabled": True, "match": {"extensions": []}},
            {"id": "r2", "name": "Rule 2", "enabled": True, "match": {"extensions": [".pdf"]}},
        ],
    }
    res2 = client.put(f"/api/v1/datasets/{dataset_id}/ingestion-policy", json=policy_v2)
    assert res2.status_code == 200, res2.text

    rolled = client.post(f"/api/v1/datasets/{dataset_id}/ingestion-policy/rollback", json={"version_id": first_version_id})
    assert rolled.status_code == 200, rolled.text
    rolled_body = rolled.json()
    assert isinstance(rolled_body.get("rules"), list)
    assert len(rolled_body["rules"]) == 1

