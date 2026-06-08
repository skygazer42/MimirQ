from __future__ import annotations

import uuid

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db


class _DummyDB:
    def __init__(self) -> None:
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1

    def refresh(self, _obj) -> None:  # noqa: ANN001
        return None


def _override_get_db():  # noqa: ANN202
    db = _DummyDB()
    yield db


def _override_get_tenant_id() -> uuid.UUID:
    return uuid.UUID("00000000-0000-0000-0000-000000000001")


def _override_get_current_account_id() -> str:
    return "test-account"


def test_dataset_retrieval_audit_put_sanitizes_and_persists(monkeypatch):  # noqa: ANN001
    from app.api.v1.datasets import put_dataset_retrieval_audit
    from app.services.dataset_service import DatasetService

    dataset_id = uuid.uuid4()

    class _Dataset:
        def __init__(self) -> None:
            self.id = dataset_id
            self.tenant_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
            self.name = "Demo"
            self.dataset_metadata = {"owner": "platform"}

    ds = _Dataset()

    monkeypatch.setattr(DatasetService, "get_dataset", lambda _db, _tenant_id, _did: ds, raising=True)
    monkeypatch.setattr(DatasetService, "assert_dataset_writable", lambda _db, _dataset, _account_id: None, raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.put("/api/v1/datasets/{dataset_id}/retrieval-audit")(put_dataset_retrieval_audit)
    client = TestClient(app)

    res = client.put(
        f"/api/v1/datasets/{dataset_id}/retrieval-audit",
        json={
            "status": "failed",
            "plugin_refs": ["plugin:demo@1.0.0:chunk", "plugin:demo@1.0.0:chunk"],
            "plugin_package_hashes": ["sha256:abc123"],
            "failure_categories": {"scope": 1, "raw_context": 99},
            "gates": [
                {
                    "name": "external_probe",
                    "status": "failed",
                    "source": "external_gate",
                    "metrics": {
                        "hit_at_1": 0.5,
                        "expected_metadata_hit_rate": 0.75,
                        "raw_context": "SHOULD_NOT_LEAK_RAW_CHUNK_TEXT",
                        "api_key": "SHOULD_NOT_LEAK_SECRET",
                    },
                    "failed_conditions": ["expected_metadata_hit_rate"],
                }
            ],
            "raw_query": "SHOULD_NOT_LEAK_QUERY",
        },
    )

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "failed"
    assert body["plugin_refs"] == ["plugin:demo@1.0.0:chunk"]
    assert body["failure_categories"] == {"scope": 1}
    assert body["gates"][0]["metrics"] == {
        "hit_at_1": 0.5,
        "expected_metadata_hit_rate": 0.75,
    }
    assert ds.dataset_metadata["owner"] == "platform"
    assert ds.dataset_metadata["retrieval_audit"] == body
    assert "SHOULD_NOT_LEAK" not in str(ds.dataset_metadata["retrieval_audit"])


def test_dataset_retrieval_audit_put_requires_writable_dataset(monkeypatch):  # noqa: ANN001
    from app.api.v1.datasets import put_dataset_retrieval_audit
    from app.services.dataset_service import DatasetService

    dataset_id = uuid.uuid4()

    class _Dataset:
        def __init__(self) -> None:
            self.id = dataset_id
            self.tenant_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
            self.dataset_metadata = {}

    ds = _Dataset()

    monkeypatch.setattr(DatasetService, "get_dataset", lambda _db, _tenant_id, _did: ds, raising=True)

    def _deny(_db, _dataset, _account_id):  # noqa: ANN001
        raise HTTPException(status_code=403, detail="No permission to manage dataset")

    monkeypatch.setattr(DatasetService, "assert_dataset_writable", _deny, raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.put("/api/v1/datasets/{dataset_id}/retrieval-audit")(put_dataset_retrieval_audit)
    client = TestClient(app)

    res = client.put(
        f"/api/v1/datasets/{dataset_id}/retrieval-audit",
        json={"status": "passed", "gates": [{"name": "external_probe", "status": "passed", "metrics": {}}]},
    )

    assert res.status_code == 403
    assert "retrieval_audit" not in ds.dataset_metadata
