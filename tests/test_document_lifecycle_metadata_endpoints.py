
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.core.database import get_db


def _build_client(monkeypatch, *, doc):  # noqa: ANN001
    import app.api.v1.document_lifecycle as lifecycle_module
    import app.api.v1.documents as documents_module
    from app.models.document import Document as DBDocument

    tenant_id = doc.tenant_id

    class _DummyQuery:
        def __init__(self, model):  # noqa: ANN001
            self.model = model

        def filter(self, *_a, **_k):  # noqa: ANN001
            return self

        def first(self):  # noqa: ANN001
            if self.model is DBDocument:
                return doc
            return None

    class _DummyDB:
        def query(self, model):  # noqa: ANN001
            return _DummyQuery(model)

        def commit(self):  # noqa: ANN001
            return None

        def refresh(self, _obj):  # noqa: ANN001
            return None

        def rollback(self):  # noqa: ANN001
            return None

    def _override_get_db():  # noqa: ANN202
        yield _DummyDB()

    def _override_get_tenant_id() -> uuid.UUID:
        return tenant_id

    def _override_get_current_account_id() -> str:
        return "test-account"

    # Bypass membership checks in unit tests (covered by dedicated RBAC tests).
    monkeypatch.setattr(lifecycle_module.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(lifecycle_module.DatasetService, "get_dataset", lambda *_a, **_k: object(), raising=True)

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id
    app.include_router(documents_module.router, prefix="/api/v1/documents")
    return TestClient(app), lifecycle_module


def test_document_lifecycle_metadata_get_and_patch(monkeypatch):  # noqa: ANN001
    doc_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()

    class _DummyDoc:
        def __init__(self) -> None:
            self.id = doc_id
            self.tenant_id = tenant_id
            self.dataset_id = dataset_id
            self.publication_status = "published"
            self.lifecycle_owner = None
            self.review_due_at = None
            self.authority_level = None
            self.supersedes_document_id = None

    dummy_doc = _DummyDoc()
    client, documents_module = _build_client(monkeypatch, doc=dummy_doc)

    # Allow writes for this test.
    monkeypatch.setattr(documents_module.DatasetService, "assert_dataset_writable", lambda *_a, **_k: None, raising=True)

    captured: list[dict] = []

    def _fake_audit_log_event(_db, *, details, **_k):  # noqa: ANN001
        captured.append(dict(details or {}))

    monkeypatch.setattr(documents_module, "audit_log_event", _fake_audit_log_event, raising=True)

    res = client.get(f"/api/v1/documents/{doc_id}/lifecycle-metadata")
    assert res.status_code == 200, res.text
    assert res.json() == {
        "lifecycle_owner": None,
        "review_due_at": None,
        "authority_level": None,
        "supersedes_document_id": None,
        "publication_status": "published",
    }

    due = datetime(2026, 3, 3, 12, 0, tzinfo=UTC)
    res2 = client.patch(
        f"/api/v1/documents/{doc_id}/lifecycle-metadata",
        json={
            "lifecycle_owner": " alice@example.com ",
            "review_due_at": due.isoformat(),
            "authority_level": 10,
        },
    )
    assert res2.status_code == 200, res2.text
    body = res2.json()
    assert body["lifecycle_owner"] == "alice@example.com"
    assert body["review_due_at"].startswith("2026-03-03T12:00:00")
    assert body["authority_level"] == 10
    assert body["publication_status"] == "published"

    assert dummy_doc.lifecycle_owner == "alice@example.com"
    assert dummy_doc.authority_level == 10
    assert dummy_doc.review_due_at == due
    assert dummy_doc.publication_status == "published"

    assert captured, "expected audit log event"
    details = captured[-1]
    assert "alice@example.com" not in str(details), "audit log must not include raw owner string"
    assert details.get("action", None) is None  # ensure details is just the details dict
    assert details.get("lifecycle_owner_hash") is not None

    # Clearing owner with blank string should normalize to null.
    res3 = client.patch(
        f"/api/v1/documents/{doc_id}/lifecycle-metadata",
        json={"lifecycle_owner": "   "},
    )
    assert res3.status_code == 200, res3.text
    assert res3.json()["lifecycle_owner"] is None
    assert dummy_doc.lifecycle_owner is None

    # Publication status patch.
    res4 = client.patch(
        f"/api/v1/documents/{doc_id}/lifecycle-metadata",
        json={"publication_status": "draft"},
    )
    assert res4.status_code == 200, res4.text
    assert res4.json()["publication_status"] == "draft"
    assert dummy_doc.publication_status == "draft"


def test_document_lifecycle_metadata_patch_denied_when_not_writable(monkeypatch):  # noqa: ANN001
    doc_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()

    class _DummyDoc:
        def __init__(self) -> None:
            self.id = doc_id
            self.tenant_id = tenant_id
            self.dataset_id = dataset_id
            self.lifecycle_owner = None
            self.review_due_at = None
            self.authority_level = None
            self.supersedes_document_id = None

    dummy_doc = _DummyDoc()
    client, documents_module = _build_client(monkeypatch, doc=dummy_doc)

    def _deny(*_a, **_k):  # noqa: ANN001
        raise HTTPException(status_code=403, detail="No dataset write permission")

    monkeypatch.setattr(documents_module.DatasetService, "assert_dataset_writable", _deny, raising=True)

    res = client.patch(
        f"/api/v1/documents/{doc_id}/lifecycle-metadata",
        json={"authority_level": 1},
    )
    assert res.status_code == 403, res.text


@pytest.mark.parametrize("bad_value", [0, "0", None])  # noqa: ANN001
def test_document_lifecycle_metadata_patch_rejects_self_supersedes(monkeypatch, bad_value):  # noqa: ANN001
    doc_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()

    class _DummyDoc:
        def __init__(self) -> None:
            self.id = doc_id
            self.tenant_id = tenant_id
            self.dataset_id = dataset_id
            self.lifecycle_owner = None
            self.review_due_at = None
            self.authority_level = None
            self.supersedes_document_id = None

    dummy_doc = _DummyDoc()
    client, documents_module = _build_client(monkeypatch, doc=dummy_doc)

    monkeypatch.setattr(documents_module.DatasetService, "assert_dataset_writable", lambda *_a, **_k: None, raising=True)

    # Use doc_id string; ensure endpoint rejects self reference regardless of other payload fields.
    payload = {"supersedes_document_id": str(doc_id)}
    if bad_value is not None:
        payload["authority_level"] = bad_value

    res = client.patch(f"/api/v1/documents/{doc_id}/lifecycle-metadata", json=payload)
    assert res.status_code in {400, 422}, res.text
    if res.status_code == 400:
        assert "supersedes_document_id" in res.text


def test_document_qa_calls_the_qa_service(monkeypatch) -> None:
    import app.api.v1.document_mutations as mutations_module
    import app.api.v1.documents as documents_module

    document_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    document = SimpleNamespace(
        id=document_id,
        tenant_id=tenant_id,
        dataset_id=None,
        owner_id="test-account",
        status="completed",
    )
    client, _lifecycle_module = _build_client(monkeypatch, doc=document)

    called: dict[str, object] = {}

    def _generate(_db, **kwargs):  # noqa: ANN001
        called.update(kwargs)
        return SimpleNamespace(mode="extract", deleted=0, created=1, chunk_ids=[], preview=[])

    monkeypatch.setattr(documents_module.DatasetService, "ensure_member", lambda *_args: None, raising=True)
    monkeypatch.setattr(documents_module, "_assert_document_writable_for_lifecycle", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(mutations_module, "audit_log_event", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(mutations_module, "generate_and_index_document_qa", _generate, raising=True)

    response = client.post(f"/api/v1/documents/{document_id}/qa/generate", json={"num_pairs": 3})

    assert response.status_code == 200, response.text
    assert response.json()["created"] == 1
    assert called["document"] is document
    assert called["num_pairs"] == 3
