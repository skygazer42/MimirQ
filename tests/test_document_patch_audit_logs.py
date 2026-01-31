from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.schemas.document import DocumentDetail
from app.core.database import get_db


class _DummyQuery:
    def __init__(self, obj):  # noqa: ANN001
        self._obj = obj

    def filter(self, *args, **kwargs):  # noqa: ANN001, ANN202
        return self

    def first(self):  # noqa: ANN202
        return self._obj


class _DummyDB:
    def __init__(self, doc):  # noqa: ANN001
        self._doc = doc

    def query(self, model):  # noqa: ANN001, ANN202
        return _DummyQuery(self._doc)

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None

    def refresh(self, obj) -> None:  # noqa: ANN001
        # Mimic a few DB defaults used by response models.
        if getattr(obj, "chunk_count", None) is None:
            obj.chunk_count = 0
        if getattr(obj, "total_characters", None) is None:
            obj.total_characters = 0
        now = datetime.now(timezone.utc)
        if getattr(obj, "created_at", None) is None:
            obj.created_at = now
        if getattr(obj, "updated_at", None) is None:
            obj.updated_at = now
        return None


def test_patch_user_metadata_emits_audit_log(monkeypatch):  # noqa: ANN001
    import app.api.v1.documents as documents_module
    from app.api.v1.documents import patch_document_user_metadata
    from app.models.document import Document as DBDocument

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    document_id = uuid.uuid4()

    doc = DBDocument(
        id=document_id,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        filename="doc.txt",
        file_type="txt",
        file_size=1,
        file_path="manual://doc",
        owner_id="test-account",
        access_mode=None,
        status="completed",
        processing_progress=100,
        doc_metadata={},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    doc.chunk_count = 0
    doc.total_characters = 0

    # Avoid permission/DB lookups in unit test.
    monkeypatch.setattr(documents_module.DatasetService, "ensure_member", lambda *args, **kwargs: None, raising=True)
    monkeypatch.setattr(documents_module.DatasetService, "get_dataset", lambda *args, **kwargs: object(), raising=True)
    monkeypatch.setattr(documents_module.DatasetService, "assert_dataset_writable", lambda *args, **kwargs: None, raising=True)

    events: list[dict] = []

    def _fake_audit_log_event(db, **kwargs):  # noqa: ANN001, ANN202
        events.append(kwargs)

    monkeypatch.setattr(documents_module, "audit_log_event", _fake_audit_log_event, raising=True)

    dummy_db = _DummyDB(doc)

    def _override_get_db():  # noqa: ANN202
        yield dummy_db

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = lambda: tenant_id
    app.dependency_overrides[get_current_account_id] = lambda: "test-account"
    app.patch("/api/v1/documents/{document_id}/metadata", response_model=DocumentDetail)(patch_document_user_metadata)
    client = TestClient(app)

    res = client.patch(
        f"/api/v1/documents/{document_id}/metadata",
        json={"patch": {"quarantine_reviewed": True, "quarantine_action": "reviewed"}, "replace": False},
    )
    assert res.status_code == 200, res.text

    assert len(events) == 1
    assert events[0]["action"] == "document.metadata.user.patch"
    assert events[0]["resource_id"] == str(document_id)
    details = events[0].get("details") or {}
    assert details.get("replace") is False
    assert "quarantine_action" in (details.get("keys") or [])


def test_patch_pipeline_emits_audit_log(monkeypatch):  # noqa: ANN001
    import app.api.v1.documents as documents_module
    from app.api.v1.documents import patch_document_pipeline
    from app.models.document import Document as DBDocument

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    document_id = uuid.uuid4()

    doc = DBDocument(
        id=document_id,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        filename="doc.txt",
        file_type="txt",
        file_size=1,
        file_path="manual://doc",
        owner_id="test-account",
        access_mode=None,
        status="completed",
        processing_progress=100,
        doc_metadata={},
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    doc.chunk_count = 0
    doc.total_characters = 0

    monkeypatch.setattr(documents_module.DatasetService, "ensure_member", lambda *args, **kwargs: None, raising=True)
    monkeypatch.setattr(documents_module.DatasetService, "get_dataset", lambda *args, **kwargs: object(), raising=True)
    monkeypatch.setattr(documents_module.DatasetService, "assert_dataset_writable", lambda *args, **kwargs: None, raising=True)

    events: list[dict] = []

    def _fake_audit_log_event(db, **kwargs):  # noqa: ANN001, ANN202
        events.append(kwargs)

    monkeypatch.setattr(documents_module, "audit_log_event", _fake_audit_log_event, raising=True)

    dummy_db = _DummyDB(doc)

    def _override_get_db():  # noqa: ANN202
        yield dummy_db

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = lambda: tenant_id
    app.dependency_overrides[get_current_account_id] = lambda: "test-account"
    app.patch("/api/v1/documents/{document_id}/pipeline", response_model=DocumentDetail)(patch_document_pipeline)
    client = TestClient(app)

    res = client.patch(
        f"/api/v1/documents/{document_id}/pipeline",
        json={"patch": {"governance_drop_outline_only": False}, "replace": False},
    )
    assert res.status_code == 200, res.text

    assert len(events) == 1
    assert events[0]["action"] == "document.pipeline.patch"
    assert events[0]["resource_id"] == str(document_id)
    details = events[0].get("details") or {}
    assert details.get("replace") is False
    assert "governance_drop_outline_only" in (details.get("fields") or [])

