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


def test_observability_index_drift_list_endpoint_calls_service(monkeypatch):  # noqa: ANN001
    import app.api.v1.observability as obs_mod
    import app.services.index_audit_service as audit_svc

    monkeypatch.setattr(obs_mod, "_ensure_admin", lambda *_args, **_kwargs: None, raising=True)

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()

    def _fake_list_index_drift_items(**_kwargs):  # noqa: ANN202
        return [
            type(
                "Row",
                (),
                {
                    "id": uuid.uuid4(),
                    "tenant_id": tenant_id,
                    "dataset_id": dataset_id,
                    "document_id": None,
                    "chunk_id": None,
                    "operation": "chunk.delete",
                    "channel": "vector",
                    "strictness": "strict",
                    "status": "open",
                    "reason": "vector delete failed",
                    "details": {},
                    "reconcile_task_id": "task-1",
                    "replay_count": 0,
                    "created_at": None,
                    "updated_at": None,
                    "resolved_at": None,
                    "resolved_by": None,
                    "resolution_note": None,
                    "last_replayed_at": None,
                },
            )()
        ]

    monkeypatch.setattr(audit_svc, "list_index_drift_items", _fake_list_index_drift_items, raising=True)

    def _override_get_tenant_id() -> uuid.UUID:
        return tenant_id

    def _override_get_current_account_id() -> str:
        return "test-account"

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id

    from app.api.v1.observability import list_index_drift

    app.get("/api/v1/observability/index-drift")(list_index_drift)
    client = TestClient(app)

    res = client.get(f"/api/v1/observability/index-drift?dataset_id={dataset_id}")
    assert res.status_code == 200, res.text
    body = res.json()

    assert body["items"][0]["dataset_id"] == str(dataset_id)
    assert body["items"][0]["operation"] == "chunk.delete"
    assert body["items"][0]["reconcile_task_id"] == "task-1"


def test_observability_index_drift_resolve_endpoint_calls_service(monkeypatch):  # noqa: ANN001
    import app.api.v1.observability as obs_mod
    import app.services.index_audit_service as audit_svc

    monkeypatch.setattr(obs_mod, "_ensure_admin", lambda *_args, **_kwargs: None, raising=True)

    tenant_id = uuid.uuid4()
    item_id = uuid.uuid4()

    def _fake_resolve_index_drift_item(**_kwargs):  # noqa: ANN202
        return type(
            "Row",
            (),
            {
                "id": item_id,
                "tenant_id": tenant_id,
                "dataset_id": None,
                "document_id": None,
                "chunk_id": None,
                "operation": "chunk.disable",
                "channel": "vector",
                "strictness": "strict",
                "status": "resolved",
                "reason": "vector delete failed",
                "details": {},
                "reconcile_task_id": "task-2",
                "replay_count": 1,
                "created_at": None,
                "updated_at": None,
                "resolved_at": None,
                "resolved_by": "ops",
                "resolution_note": "rebuilt",
                "last_replayed_at": None,
            },
        )()

    monkeypatch.setattr(audit_svc, "resolve_index_drift_item", _fake_resolve_index_drift_item, raising=True)

    def _override_get_tenant_id() -> uuid.UUID:
        return tenant_id

    def _override_get_current_account_id() -> str:
        return "ops"

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id

    from app.api.v1.observability import resolve_index_drift

    app.post("/api/v1/observability/index-drift/{item_id}/resolve")(resolve_index_drift)
    client = TestClient(app)

    res = client.post(
        f"/api/v1/observability/index-drift/{item_id}/resolve",
        json={"resolution_note": "rebuilt"},
    )
    assert res.status_code == 200, res.text
    body = res.json()

    assert body["id"] == str(item_id)
    assert body["status"] == "resolved"
    assert body["resolution_note"] == "rebuilt"
