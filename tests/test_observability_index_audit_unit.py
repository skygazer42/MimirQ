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


def test_observability_index_audit_endpoint_calls_service(monkeypatch):  # noqa: ANN001
    import app.api.v1.observability as obs_mod
    import app.services.index_audit_service as audit_svc

    # Bypass role checks.
    monkeypatch.setattr(obs_mod, "_ensure_admin", lambda *_args, **_kwargs: None, raising=True)

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()

    def _fake_run_dataset_index_audit(**_kwargs):  # noqa: ANN202
        return {
            "tenant_id": str(tenant_id),
            "dataset_id": str(dataset_id),
            "vector_backend": "milvus",
            "active_documents": 1,
            "active_chunks": 2,
            "vector_id_missing": 0,
            "vector_ids_checked": 2,
            "vector_ids_missing_in_backend": 0,
            "vector_ids_missing_in_backend_sample": [],
            "milvus_ids_sampled": 0,
            "milvus_orphan_ids_sample": [],
        }

    monkeypatch.setattr(audit_svc, "run_dataset_index_audit", _fake_run_dataset_index_audit, raising=True)

    def _override_get_tenant_id() -> uuid.UUID:
        return tenant_id

    def _override_get_current_account_id() -> str:
        return "test-account"

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id

    from app.api.v1.observability import get_index_audit

    app.get("/api/v1/observability/index-audit")(get_index_audit)
    client = TestClient(app)

    res = client.get(f"/api/v1/observability/index-audit?dataset_id={dataset_id}")
    assert res.status_code == 200, res.text
    body = res.json()

    assert body["tenant_id"] == str(tenant_id)
    assert body["dataset_id"] == str(dataset_id)
    assert body["active_chunks"] == 2

