from __future__ import annotations

import json
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db


class _DummyDB:
    def commit(self) -> None:
        return None

    def refresh(self, obj) -> None:  # noqa: ANN001
        return None


def _override_get_db():  # noqa: ANN202
    yield _DummyDB()


def _override_get_tenant_id() -> uuid.UUID:
    return uuid.uuid4()


def _override_get_current_account_id() -> str:
    return "test-account"


def test_dataset_ingestion_policy_put_get_and_import_export(monkeypatch):  # noqa: ANN001
    from app.api.v1.datasets import (
        export_dataset_ingestion_policy,
        get_dataset_ingestion_policy,
        import_dataset_ingestion_policy,
        put_dataset_ingestion_policy,
    )
    from app.services.dataset_service import DatasetService

    # Keep a single in-memory dataset object to observe metadata mutations.
    dataset_id = uuid.uuid4()

    class _Dataset:
        def __init__(self) -> None:
            self.id = dataset_id
            self.tenant_id = uuid.uuid4()
            self.name = "Demo"
            self.dataset_metadata = {}

    ds = _Dataset()

    monkeypatch.setattr(DatasetService, "get_dataset", lambda db, tenant_id, did: ds, raising=True)
    monkeypatch.setattr(DatasetService, "assert_dataset_readable", lambda db, dataset, account_id: None, raising=True)
    monkeypatch.setattr(DatasetService, "assert_dataset_writable", lambda db, dataset, account_id: None, raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id

    app.get("/api/v1/datasets/{dataset_id}/ingestion-policy")(get_dataset_ingestion_policy)
    app.put("/api/v1/datasets/{dataset_id}/ingestion-policy")(put_dataset_ingestion_policy)
    app.post("/api/v1/datasets/{dataset_id}/ingestion-policy/import")(import_dataset_ingestion_policy)
    app.get("/api/v1/datasets/{dataset_id}/ingestion-policy/export")(export_dataset_ingestion_policy)

    client = TestClient(app)

    payload = {
        "version": "1",
        "rules": [
            {
                "id": "pdf-default",
                "name": "PDF Default",
                "enabled": True,
                "match": {"extensions": [".pdf"]},
                "preprocess": {"enabled": False, "steps": []},
                "parser_backend": "auto",
                "governance_profile_ref": "builtin:pdf_text",
                "pipeline_patch": {"governance_enabled": True},
            }
        ],
    }

    res = client.put(f"/api/v1/datasets/{dataset_id}/ingestion-policy", json=payload)
    assert res.status_code == 200
    assert res.json()["version"] == "1"
    assert len(res.json()["rules"]) == 1
    assert "ingestion_policy" in ds.dataset_metadata

    res = client.get(f"/api/v1/datasets/{dataset_id}/ingestion-policy")
    assert res.status_code == 200
    assert res.json()["version"] == "1"
    assert len(res.json()["rules"]) == 1

    # Import (replace=true)
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    res = client.post(
        f"/api/v1/datasets/{dataset_id}/ingestion-policy/import",
        data={"replace": "true"},
        files={"file": ("policy.json", body, "application/json")},
    )
    assert res.status_code == 200
    assert res.json()["rule_count"] == 1

    # Export
    res = client.get(f"/api/v1/datasets/{dataset_id}/ingestion-policy/export")
    assert res.status_code == 200
    exported = json.loads(res.content.decode("utf-8"))
    assert exported["version"] == "1"
    assert len(exported["rules"]) == 1


def test_dataset_ingestion_policy_import_replace_false_conflict(monkeypatch):  # noqa: ANN001
    from app.api.v1.datasets import import_dataset_ingestion_policy
    from app.services.dataset_service import DatasetService

    dataset_id = uuid.uuid4()

    class _Dataset:
        def __init__(self) -> None:
            self.id = dataset_id
            self.tenant_id = uuid.uuid4()
            self.name = "Demo"
            self.dataset_metadata = {"ingestion_policy": {"version": "1", "rules": []}}

    ds = _Dataset()

    monkeypatch.setattr(DatasetService, "get_dataset", lambda db, tenant_id, did: ds, raising=True)
    monkeypatch.setattr(DatasetService, "assert_dataset_writable", lambda db, dataset, account_id: None, raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.post("/api/v1/datasets/{dataset_id}/ingestion-policy/import")(import_dataset_ingestion_policy)
    client = TestClient(app)

    res = client.post(
        f"/api/v1/datasets/{dataset_id}/ingestion-policy/import",
        data={"replace": "false"},
        files={"file": ("policy.json", b'{"version":"1","rules":[]}', "application/json")},
    )
    assert res.status_code == 409
