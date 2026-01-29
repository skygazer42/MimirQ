from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db


def test_document_timeline_returns_events(monkeypatch):  # noqa: ANN001
    import app.api.v1.documents as documents_module
    from app.models.audit_log import AuditLog
    from app.models.document import Document as DBDocument

    tenant_id = uuid.uuid4()
    doc_id = uuid.uuid4()

    class _DummyDoc:
        def __init__(self) -> None:
            self.id = doc_id
            self.tenant_id = tenant_id
            self.dataset_id = None
            self.status = "processing"
            self.current_stage = "parsing"
            self.processing_progress = 12
            self.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
            self.updated_at = datetime(2026, 1, 2, tzinfo=timezone.utc)

    dummy_doc = _DummyDoc()

    class _DummyAudit:
        def __init__(self, action: str) -> None:
            self.id = uuid.uuid4()
            self.tenant_id = tenant_id
            self.action = action
            self.resource_type = "document"
            self.resource_id = str(doc_id)
            self.request_id = "req_test"
            self.details = {"stage": "parsing"}
            self.created_at = datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc)

    dummy_audits = [_DummyAudit("document.parse.started")]

    class _DummyQuery:
        def __init__(self, model):  # noqa: ANN001
            self.model = model
            self._limit: int | None = None

        def filter(self, *_a, **_k):  # noqa: ANN001
            return self

        def order_by(self, *_a, **_k):  # noqa: ANN001
            return self

        def limit(self, n: int):  # noqa: ANN001
            self._limit = n
            return self

        def all(self):  # noqa: ANN001
            if self.model is AuditLog:
                return list(dummy_audits)[: (self._limit or len(dummy_audits))]
            return []

        def first(self):  # noqa: ANN001
            if self.model is DBDocument:
                return dummy_doc
            return None

    class _DummyDB:
        def query(self, model):  # noqa: ANN001
            return _DummyQuery(model)

    def _override_get_db():  # noqa: ANN202
        yield _DummyDB()

    def _override_get_tenant_id() -> uuid.UUID:
        return tenant_id

    def _override_get_current_account_id() -> str:
        return "test-account"

    # Bypass permission enforcement for unit test (covered elsewhere).
    monkeypatch.setattr(documents_module.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(documents_module.DatasetService, "assert_dataset_readable", lambda *_a, **_k: None, raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.include_router(documents_module.router, prefix="/api/v1/documents")
    client = TestClient(app)

    res = client.get(f"/api/v1/documents/{doc_id}/timeline")
    assert res.status_code == 200, res.text
    body = res.json()
    assert isinstance(body.get("items"), list)
    assert len(body["items"]) >= 1

