from __future__ import annotations

import asyncio
import uuid
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db
from app.services.dataset_service import DatasetService


class _Member:
    def __init__(self, role: str):
        self.role = role


class _FakeQuery:
    def __init__(self, *, count: int = 0, all_rows=None):  # noqa: ANN001
        self._count = int(count or 0)
        self._all = list(all_rows or [])

    def filter(self, *_a, **_k):  # noqa: ANN001
        return self

    def order_by(self, *_a, **_k):  # noqa: ANN001
        return self

    def limit(self, *_a, **_k):  # noqa: ANN001
        return self

    def count(self) -> int:
        return int(self._count)

    def all(self):  # noqa: ANN001
        return list(self._all)


class _FakeDB:
    def __init__(self, queries):  # noqa: ANN001
        self._queries = list(queries)
        self.commits = 0

    def query(self, *_a, **_k):  # noqa: ANN001
        if not self._queries:
            raise AssertionError("Unexpected db.query call")
        return self._queries.pop(0)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        return


def _override_get_tenant_id() -> uuid.UUID:
    return uuid.UUID(int=1)


def _override_get_current_account_id() -> str:
    return "test-account"


def test_dataset_purge_denies_non_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.v1.datasets import purge_dataset_documents

    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_a, **_k: _Member("viewer"), raising=True)

    db = _FakeDB([])

    def _override_get_db():  # noqa: ANN202
        yield db

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.post("/api/v1/datasets/{dataset_id}/purge")(purge_dataset_documents)
    client = TestClient(app)

    res = client.post("/api/v1/datasets/00000000-0000-0000-0000-000000000002/purge?dry_run=true&max_delete=10")
    assert res.status_code == 403, res.text


def test_dataset_purge_dry_run_plans_only(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.datasets as datasets_mod
    from app.api.v1.datasets import purge_dataset_documents

    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_a, **_k: _Member("admin"), raising=True)

    # Avoid deep dataset permission checks for this unit test.
    ds = SimpleNamespace(id=UUID(int=2), tenant_id=UUID(int=1), name="ds", permission="all_team_members", owner_id="u")
    monkeypatch.setattr(DatasetService, "get_dataset", lambda *_a, **_k: ds, raising=True)
    monkeypatch.setattr(DatasetService, "assert_dataset_writable", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(datasets_mod, "audit_log_event", lambda *_a, **_k: None, raising=True)

    deleted_ids: list[UUID] = []

    async def _fake_delete_document(*, document_id: UUID, **_k):  # noqa: ANN001
        await asyncio.sleep(0)  # Sonar S7503
        deleted_ids.append(UUID(str(document_id)))
        return None

    import app.api.v1.documents as docs_mod

    monkeypatch.setattr(docs_mod, "delete_document", _fake_delete_document, raising=True)

    db = _FakeDB(
        queries=[
            _FakeQuery(count=0),  # active_profile_scans
            _FakeQuery(count=0),  # active_precheck_scans
            _FakeQuery(all_rows=[(UUID(int=10),), (UUID(int=11),)]),  # document ids
        ]
    )

    def _override_get_db():  # noqa: ANN202
        yield db

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.post("/api/v1/datasets/{dataset_id}/purge")(purge_dataset_documents)
    client = TestClient(app)

    res = client.post("/api/v1/datasets/00000000-0000-0000-0000-000000000002/purge?dry_run=true&max_delete=10")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body.get("dry_run") is True
    assert body.get("eligible") == 2
    assert body.get("deleted") == 0
    assert deleted_ids == []


def test_dataset_purge_executes_delete_document(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.datasets as datasets_mod
    from app.api.v1.datasets import purge_dataset_documents

    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_a, **_k: _Member("admin"), raising=True)

    ds = SimpleNamespace(id=UUID(int=2), tenant_id=UUID(int=1), name="ds", permission="all_team_members", owner_id="u")
    monkeypatch.setattr(DatasetService, "get_dataset", lambda *_a, **_k: ds, raising=True)
    monkeypatch.setattr(DatasetService, "assert_dataset_writable", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(datasets_mod, "audit_log_event", lambda *_a, **_k: None, raising=True)

    deleted_ids: list[UUID] = []

    async def _fake_delete_document(*, document_id: UUID, **_k):  # noqa: ANN001
        await asyncio.sleep(0)  # Sonar S7503
        deleted_ids.append(UUID(str(document_id)))
        return None

    import app.api.v1.documents as docs_mod

    monkeypatch.setattr(docs_mod, "_delete_document_lifecycle", _fake_delete_document, raising=False)

    db = _FakeDB(
        queries=[
            _FakeQuery(count=0),  # active_profile_scans
            _FakeQuery(count=0),  # active_precheck_scans
            _FakeQuery(all_rows=[(UUID(int=10),), (UUID(int=11),)]),  # document ids
        ]
    )

    def _override_get_db():  # noqa: ANN202
        yield db

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.post("/api/v1/datasets/{dataset_id}/purge")(purge_dataset_documents)
    client = TestClient(app)

    res = client.post("/api/v1/datasets/00000000-0000-0000-0000-000000000002/purge?dry_run=false&max_delete=10")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body.get("dry_run") is False
    assert body.get("eligible") == 2
    assert body.get("deleted") == 2
    assert deleted_ids == [UUID(int=10), UUID(int=11)]


def test_dataset_purge_admin_does_not_require_dataset_writable(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Purge is an admin-only lifecycle endpoint; it should not require dataset write permission
    (e.g. for private datasets owned by a different user).
    """
    from fastapi import HTTPException

    import app.api.v1.datasets as datasets_mod
    from app.api.v1.datasets import purge_dataset_documents

    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_a, **_k: _Member("admin"), raising=True)

    ds = SimpleNamespace(
        id=UUID(int=2),
        tenant_id=UUID(int=1),
        name="ds",
        permission="only_me",
        owner_id="someone-else",
    )
    monkeypatch.setattr(DatasetService, "get_dataset", lambda *_a, **_k: ds, raising=True)

    def _deny_dataset_write(*_a, **_k):  # noqa: ANN001
        raise HTTPException(status_code=403, detail="No dataset write permission")

    monkeypatch.setattr(DatasetService, "assert_dataset_writable", _deny_dataset_write, raising=True)
    monkeypatch.setattr(datasets_mod, "audit_log_event", lambda *_a, **_k: None, raising=True)

    db = _FakeDB(
        queries=[
            _FakeQuery(count=0),  # active_profile_scans
            _FakeQuery(count=0),  # active_precheck_scans
            _FakeQuery(all_rows=[(UUID(int=10),), (UUID(int=11),)]),  # document ids
        ]
    )

    def _override_get_db():  # noqa: ANN202
        yield db

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.post("/api/v1/datasets/{dataset_id}/purge")(purge_dataset_documents)
    client = TestClient(app)

    res = client.post("/api/v1/datasets/00000000-0000-0000-0000-000000000002/purge?dry_run=true&max_delete=10")
    assert res.status_code == 200, res.text


def test_dataset_purge_deletes_even_if_public_delete_is_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Purge is a lifecycle/admin endpoint; it should delete using an internal lifecycle path
    even if the public delete endpoint would deny due to dataset permissions.
    """
    from fastapi import HTTPException

    import app.api.v1.datasets as datasets_mod
    import app.api.v1.documents as docs_mod
    from app.api.v1.datasets import purge_dataset_documents

    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_a, **_k: _Member("admin"), raising=True)

    ds = SimpleNamespace(id=UUID(int=2), tenant_id=UUID(int=1), name="ds", permission="only_me", owner_id="u")
    monkeypatch.setattr(DatasetService, "get_dataset", lambda *_a, **_k: ds, raising=True)
    monkeypatch.setattr(datasets_mod, "audit_log_event", lambda *_a, **_k: None, raising=True)

    async def _deny_public_delete(*_a, **_k):  # noqa: ANN001
        await asyncio.sleep(0)  # Sonar S7503
        raise HTTPException(status_code=403, detail="No dataset write permission")

    monkeypatch.setattr(docs_mod, "delete_document", _deny_public_delete, raising=True)

    deleted_ids: list[UUID] = []

    async def _force_delete_document(*, document_id: UUID, **_k):  # noqa: ANN001
        await asyncio.sleep(0)  # Sonar S7503
        deleted_ids.append(UUID(str(document_id)))
        return None

    # Note: this attribute doesn't exist yet; test ensures purge uses it instead of delete_document.
    monkeypatch.setattr(docs_mod, "_delete_document_lifecycle", _force_delete_document, raising=False)

    db = _FakeDB(
        queries=[
            _FakeQuery(count=0),  # active_profile_scans
            _FakeQuery(count=0),  # active_precheck_scans
            _FakeQuery(all_rows=[(UUID(int=10),), (UUID(int=11),)]),  # document ids
        ]
    )

    def _override_get_db():  # noqa: ANN202
        yield db

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.post("/api/v1/datasets/{dataset_id}/purge")(purge_dataset_documents)
    client = TestClient(app)

    res = client.post("/api/v1/datasets/00000000-0000-0000-0000-000000000002/purge?dry_run=false&max_delete=10")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body.get("eligible") == 2
    assert body.get("deleted") == 2
    assert body.get("denied") == 0
    assert deleted_ids == [UUID(int=10), UUID(int=11)]


def test_dataset_purge_conflicts_when_scans_active(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.datasets as datasets_mod
    from app.api.v1.datasets import purge_dataset_documents

    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_a, **_k: _Member("admin"), raising=True)

    ds = SimpleNamespace(id=UUID(int=2), tenant_id=UUID(int=1), name="ds", permission="all_team_members", owner_id="u")
    monkeypatch.setattr(DatasetService, "get_dataset", lambda *_a, **_k: ds, raising=True)
    monkeypatch.setattr(datasets_mod, "audit_log_event", lambda *_a, **_k: None, raising=True)

    db = _FakeDB(
        queries=[
            _FakeQuery(count=1),  # active_profile_scans
            _FakeQuery(count=0),  # active_precheck_scans
        ]
    )

    def _override_get_db():  # noqa: ANN202
        yield db

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.post("/api/v1/datasets/{dataset_id}/purge")(purge_dataset_documents)
    client = TestClient(app)

    res = client.post("/api/v1/datasets/00000000-0000-0000-0000-000000000002/purge?dry_run=true&max_delete=10")
    assert res.status_code == 409, res.text


def test_dataset_purge_emits_audit_log_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.datasets as datasets_mod
    from app.api.v1.datasets import purge_dataset_documents

    monkeypatch.setattr(DatasetService, "ensure_member", lambda *_a, **_k: _Member("admin"), raising=True)

    ds = SimpleNamespace(id=UUID(int=2), tenant_id=UUID(int=1), name="ds", permission="all_team_members", owner_id="u")
    monkeypatch.setattr(DatasetService, "get_dataset", lambda *_a, **_k: ds, raising=True)

    captured: list[dict] = []

    def _capture_audit_event(db, *, action: str, details: dict, **_k):  # noqa: ANN001
        captured.append({"action": action, "details": dict(details or {})})
        return None

    monkeypatch.setattr(datasets_mod, "audit_log_event", _capture_audit_event, raising=True)

    db = _FakeDB(
        queries=[
            _FakeQuery(count=0),  # active_profile_scans
            _FakeQuery(count=0),  # active_precheck_scans
            _FakeQuery(all_rows=[(UUID(int=10),), (UUID(int=11),)]),  # document ids
        ]
    )

    def _override_get_db():  # noqa: ANN202
        yield db

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.post("/api/v1/datasets/{dataset_id}/purge")(purge_dataset_documents)
    client = TestClient(app)

    res = client.post("/api/v1/datasets/00000000-0000-0000-0000-000000000002/purge?dry_run=true&max_delete=10")
    assert res.status_code == 200, res.text
    assert db.commits == 1
    assert len(captured) == 1
    assert captured[0]["action"] == "dataset.purge"
    assert captured[0]["details"]["dry_run"] is True
    assert captured[0]["details"]["eligible"] == 2
