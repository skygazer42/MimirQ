import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db


class _DummyDB:
    readable_dataset_ids: list[uuid.UUID] = []

    class _ScalarResult:
        def __init__(self, items: list[uuid.UUID]) -> None:
            self._items = list(items)

        def all(self) -> list[uuid.UUID]:
            return list(self._items)

    def commit(self) -> None:
        return None

    def refresh(self, _obj) -> None:  # noqa: ANN001
        return None

    def scalars(self, _statement):  # noqa: ANN001
        return self._ScalarResult(self.readable_dataset_ids)


def _override_get_db():  # noqa: ANN202
    yield _DummyDB()


class _DummyMember:
    def __init__(self, role: str) -> None:
        self.role = role


class _Row:
    def __init__(
        self,
        *,
        id: str,
        tenant_id: uuid.UUID,
        dataset_id: uuid.UUID | None,
        name: str,
        description: str | None,
        payload: dict,
    ) -> None:
        self.id = uuid.UUID(id)
        self.tenant_id = tenant_id
        self.dataset_id = dataset_id
        self.name = name
        self.description = description
        self.payload = payload


class _ChunkPresetStore:
    def __init__(self) -> None:
        self.rows: dict[str, _Row] = {}

    def list_rows(
        self,
        *,
        db,
        tenant_id: uuid.UUID,
        q: str | None,
        limit: int,
        dataset_id: uuid.UUID | None,
        include_global: bool,
        readable_dataset_ids: set[uuid.UUID] | None,
    ):  # noqa: ANN001, ARG002
        rows = list(self.rows.values())
        if dataset_id is None and readable_dataset_ids is not None:
            allowed_dataset_ids = {None} | set(readable_dataset_ids)
            rows = [row for row in rows if getattr(row, "dataset_id", None) in allowed_dataset_ids]
        if dataset_id is None:
            return rows
        if include_global:
            return [row for row in rows if getattr(row, "dataset_id", None) in {None, dataset_id}]
        return [row for row in rows if getattr(row, "dataset_id", None) == dataset_id]

    def get_row(self, *, db, tenant_id: uuid.UUID, preset_id: str):  # noqa: ANN001, ARG002
        return self.rows.get(preset_id)

    def create_row(
        self,
        *,
        db,
        tenant_id: uuid.UUID,
        dataset_id: uuid.UUID | None,
        name: str,
        description: str | None,
        payload: dict,
    ):  # noqa: ANN001, ARG002
        preset_id = str(uuid.uuid4())
        row = _Row(
            id=preset_id,
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            name=name,
            description=description,
            payload=payload,
        )
        self.rows[preset_id] = row
        return row

    def update_row(
        self,
        *,
        db,
        tenant_id: uuid.UUID,
        preset_id: str,
        dataset_id: uuid.UUID | None,
        name: str,
        description: str | None,
        payload: dict,
    ):  # noqa: ANN001, ARG002
        row = self.rows.get(preset_id)
        if row is None:
            return None
        row.dataset_id = dataset_id
        row.name = name
        row.description = description
        row.payload = payload
        return row

    def delete_row(self, *, db, tenant_id: uuid.UUID, preset_id: str) -> bool:  # noqa: ANN001, ARG002
        return self.rows.pop(preset_id, None) is not None


def _build_chunk_presets_client(  # noqa: ANN202
    monkeypatch,
    *,
    chunk_presets_module,
    tenant_id: uuid.UUID,
    dataset_access: dict[str, dict[str, bool]],
    current_role: dict[str, str],
    store: _ChunkPresetStore,
):
    def _override_get_tenant_id() -> uuid.UUID:
        return tenant_id

    def _override_get_current_account_id() -> str:
        return "test-account"

    def _get_dataset(_db, _tenant_id, requested_dataset_id):  # noqa: ANN001
        key = str(requested_dataset_id)
        if key not in dataset_access:
            raise AssertionError(f"unexpected dataset lookup: {key}")
        return {"id": requested_dataset_id}

    def _assert_dataset_readable(_db, dataset, _account_id):  # noqa: ANN001
        if not dataset_access[str(dataset["id"])]["readable"]:
            raise chunk_presets_module.HTTPException(status_code=403, detail="No dataset access")

    def _assert_dataset_writable(_db, dataset, _account_id):  # noqa: ANN001
        if not dataset_access[str(dataset["id"])]["writable"]:
            raise chunk_presets_module.HTTPException(status_code=403, detail="No dataset write permission")

    monkeypatch.setattr(
        chunk_presets_module.DatasetService,
        "ensure_member",
        lambda *_a, **_k: _DummyMember(str(current_role.get("role") or "")),
        raising=True,
    )
    monkeypatch.setattr(chunk_presets_module.DatasetService, "get_dataset", _get_dataset, raising=True)
    monkeypatch.setattr(
        chunk_presets_module.DatasetService,
        "assert_dataset_readable",
        _assert_dataset_readable,
        raising=True,
    )
    monkeypatch.setattr(
        chunk_presets_module.DatasetService,
        "assert_dataset_writable",
        _assert_dataset_writable,
        raising=True,
    )
    monkeypatch.setattr(chunk_presets_module, "_list_chunk_preset_rows", store.list_rows, raising=True)
    monkeypatch.setattr(chunk_presets_module, "_get_chunk_preset_row", store.get_row, raising=True)
    monkeypatch.setattr(chunk_presets_module, "_create_chunk_preset_row", store.create_row, raising=True)
    monkeypatch.setattr(chunk_presets_module, "_update_chunk_preset_row", store.update_row, raising=True)
    monkeypatch.setattr(chunk_presets_module, "_delete_chunk_preset_row", store.delete_row, raising=True)

    _DummyDB.readable_dataset_ids = [uuid.UUID(key) for key, acl in dataset_access.items() if acl["readable"]]

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.include_router(chunk_presets_module.router, prefix="/api/v1/chunk-presets")
    return TestClient(app)


def test_chunk_presets_crud(monkeypatch):  # noqa: ANN001
    import app.api.v1.chunk_presets as chunk_presets_module

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()

    # Bypass tenant membership DB checks (and ensure we can pass governance checks).
    current_role = {"role": "owner"}
    dataset_access = {
        str(dataset_id): {"readable": True, "writable": True},
        str(uuid.uuid4()): {"readable": False, "writable": False},
    }
    store = _ChunkPresetStore()
    client = _build_chunk_presets_client(
        monkeypatch,
        chunk_presets_module=chunk_presets_module,
        tenant_id=tenant_id,
        dataset_access=dataset_access,
        current_role=current_role,
        store=store,
    )

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

    # Dataset-scoped preset: should be listable via dataset_id and include_global.
    res = client.post(
        "/api/v1/chunk-presets",
        json={
            "name": "Dataset Default",
            "description": "Scoped",
            "payload": {
                "dataset_id": str(dataset_id),
                "chunk_size": 1200,
                "chunk_overlap": 120,
                "chunk_strategy": "langchain_recursive",
            },
        },
    )
    assert res.status_code == 201, res.text
    preset_id_scoped = res.json()["id"]

    hidden_dataset_id = next(uuid.UUID(key) for key, acl in dataset_access.items() if not acl["readable"])
    res = client.post(
        "/api/v1/chunk-presets",
        json={
            "name": "Hidden Dataset Default",
            "description": "Hidden",
            "payload": {
                "dataset_id": str(hidden_dataset_id),
                "chunk_size": 900,
                "chunk_overlap": 90,
                "chunk_strategy": "langchain_recursive",
            },
        },
    )
    assert res.status_code == 403, res.text

    hidden_preset = store.create_row(
        db=None,
        tenant_id=tenant_id,
        dataset_id=hidden_dataset_id,
        name="Hidden preset",
        description="Should be filtered",
        payload={"dataset_id": str(hidden_dataset_id), "chunk_size": 800},
    )

    # Governance: a non-editor should not be able to "unscope" a dataset preset by omitting payload.dataset_id.
    current_role["role"] = "viewer"
    res = client.put(
        f"/api/v1/chunk-presets/{preset_id_scoped}",
        json={
            "name": "Dataset Default v2",
            "description": "Scoped but attempted unscope",
            "payload": {"chunk_size": 1200, "chunk_overlap": 120, "chunk_strategy": "langchain_recursive"},
        },
    )
    assert res.status_code == 403, res.text

    current_role["role"] = "owner"
    res = client.get("/api/v1/chunk-presets")
    assert res.status_code == 200, res.text
    ids = {x["id"] for x in (res.json().get("items") or [])}
    assert hidden_preset.id.hex not in {uuid.UUID(pid).hex for pid in ids}

    res = client.get(f"/api/v1/chunk-presets?dataset_id={dataset_id}&include_global=true")
    assert res.status_code == 200, res.text
    ids = {x["id"] for x in (res.json().get("items") or [])}
    assert ids == {preset_id, preset_id_scoped}

    res = client.get(f"/api/v1/chunk-presets?dataset_id={hidden_dataset_id}&include_global=true")
    assert res.status_code == 403, res.text

    res = client.get(f"/api/v1/chunk-presets?dataset_id={dataset_id}&include_global=false")
    assert res.status_code == 200, res.text
    ids = {x["id"] for x in (res.json().get("items") or [])}
    assert ids == {preset_id_scoped}

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

    res = client.put(
        f"/api/v1/chunk-presets/{preset_id_scoped}",
        json={
            "name": "Hidden move",
            "description": "Denied",
            "payload": {
                "dataset_id": str(hidden_dataset_id),
                "chunk_size": 1200,
                "chunk_overlap": 120,
                "chunk_strategy": "langchain_recursive",
            },
        },
    )
    assert res.status_code == 403, res.text

    res = client.delete(f"/api/v1/chunk-presets/{preset_id}")
    assert res.status_code == 204, res.text

    dataset_access[str(dataset_id)]["writable"] = False
    res = client.delete(f"/api/v1/chunk-presets/{preset_id_scoped}")
    assert res.status_code == 403, res.text
    dataset_access[str(dataset_id)]["writable"] = True

    res = client.get("/api/v1/chunk-presets")
    assert res.status_code == 200, res.text
    items = res.json().get("items") or []
    assert len(items) == 1
    assert items[0]["id"] == preset_id_scoped

    res = client.delete(f"/api/v1/chunk-presets/{preset_id_scoped}")
    assert res.status_code == 204, res.text

    res = client.get("/api/v1/chunk-presets")
    assert res.status_code == 200, res.text
    assert (res.json().get("items") or []) == []
