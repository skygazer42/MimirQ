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

    def refresh(self, _obj) -> None:  # noqa: ANN001
        return None


def _override_get_db():  # noqa: ANN202
    yield _DummyDB()


def test_chunk_presets_crud(monkeypatch):  # noqa: ANN001
    import app.api.v1.chunk_presets as chunk_presets_module

    tenant_id = uuid.uuid4()

    def _override_get_tenant_id() -> uuid.UUID:
        return tenant_id

    def _override_get_current_account_id() -> str:
        return "test-account"

    # Bypass tenant membership DB checks.
    monkeypatch.setattr(chunk_presets_module.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)

    store: dict[str, object] = {}

    class _Row:
        def __init__(self, *, id: str, tenant_id: uuid.UUID, name: str, description: str | None, payload: dict) -> None:
            self.id = uuid.UUID(id)
            self.tenant_id = tenant_id
            self.name = name
            self.description = description
            self.payload = payload

    def _list_rows(*, db, tenant_id: uuid.UUID, q: str | None, limit: int):  # noqa: ANN001
        return list(store.values())

    def _get_row(*, db, tenant_id: uuid.UUID, preset_id: str):  # noqa: ANN001
        return store.get(preset_id)

    def _create_row(*, db, tenant_id: uuid.UUID, name: str, description: str | None, payload: dict):  # noqa: ANN001
        pid = str(uuid.uuid4())
        row = _Row(id=pid, tenant_id=tenant_id, name=name, description=description, payload=payload)
        store[pid] = row
        return row

    def _update_row(*, db, tenant_id: uuid.UUID, preset_id: str, name: str, description: str | None, payload: dict):  # noqa: ANN001
        row = store.get(preset_id)
        if not row:
            return None
        row.name = name
        row.description = description
        row.payload = payload
        return row

    def _delete_row(*, db, tenant_id: uuid.UUID, preset_id: str) -> bool:  # noqa: ANN001
        return store.pop(preset_id, None) is not None

    monkeypatch.setattr(chunk_presets_module, "_list_chunk_preset_rows", _list_rows, raising=True)
    monkeypatch.setattr(chunk_presets_module, "_get_chunk_preset_row", _get_row, raising=True)
    monkeypatch.setattr(chunk_presets_module, "_create_chunk_preset_row", _create_row, raising=True)
    monkeypatch.setattr(chunk_presets_module, "_update_chunk_preset_row", _update_row, raising=True)
    monkeypatch.setattr(chunk_presets_module, "_delete_chunk_preset_row", _delete_row, raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.include_router(chunk_presets_module.router, prefix="/api/v1/chunk-presets")

    client = TestClient(app)

    payload = {
        "name": "Default",
        "description": "General KB",
        "payload": {"chunk_size": 1000, "chunk_overlap": 200, "chunk_strategy": "langchain_recursive"},
    }
    res = client.post("/api/v1/chunk-presets", json=payload)
    assert res.status_code == 201, res.text
    created = res.json()
    assert created["name"] == "Default"
    assert created["payload"]["chunk_size"] == 1000
    preset_id = created["id"]

    res = client.get("/api/v1/chunk-presets")
    assert res.status_code == 200, res.text
    items = res.json().get("items") or []
    assert len(items) == 1
    assert items[0]["id"] == preset_id

    res = client.put(
        f"/api/v1/chunk-presets/{preset_id}",
        json={
            "name": "Default v2",
            "description": None,
            "payload": {"chunk_size": 1200, "chunk_overlap": 120, "chunk_strategy": "langchain_recursive"},
        },
    )
    assert res.status_code == 200, res.text
    updated = res.json()
    assert updated["name"] == "Default v2"
    assert updated["payload"]["chunk_size"] == 1200

    res = client.delete(f"/api/v1/chunk-presets/{preset_id}")
    assert res.status_code == 204, res.text

    res = client.get("/api/v1/chunk-presets")
    assert res.status_code == 200, res.text
    assert (res.json().get("items") or []) == []
