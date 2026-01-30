from __future__ import annotations

import asyncio
import uuid
from datetime import datetime

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


def test_document_lifecycle_batch_enable_disable_archive(monkeypatch):  # noqa: ANN001
    import app.api.v1.documents as documents_module

    tenant_id = uuid.uuid4()
    doc1_id = uuid.uuid4()
    doc2_id = uuid.uuid4()
    missing_id = uuid.uuid4()

    class _Doc:
        def __init__(self, doc_id: uuid.UUID) -> None:
            self.id = doc_id
            self.tenant_id = tenant_id
            self.dataset_id = None
            self.disabled_at = None
            self.archived_at = None

    docs = {doc1_id: _Doc(doc1_id), doc2_id: _Doc(doc2_id)}

    def _override_get_tenant_id() -> uuid.UUID:
        return tenant_id

    def _override_get_current_account_id() -> str:
        return "test-account"

    monkeypatch.setattr(documents_module.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(documents_module, "_assert_document_writable_for_lifecycle", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(
        documents_module,
        "_get_document_for_lifecycle",
        lambda _db, _tenant_id, doc_id: docs.get(doc_id),
        raising=True,
    )

    app = FastAPI()
    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_tenant_id] = _override_get_tenant_id
    app.dependency_overrides[get_current_account_id] = _override_get_current_account_id

    app.post("/api/v1/documents/batch/disable")(documents_module.batch_disable_documents)
    app.post("/api/v1/documents/batch/enable")(documents_module.batch_enable_documents)
    app.post("/api/v1/documents/batch/archive")(documents_module.batch_archive_documents)
    app.post("/api/v1/documents/batch/unarchive")(documents_module.batch_unarchive_documents)

    client = TestClient(app)

    res = client.post(
        "/api/v1/documents/batch/disable",
        json={"document_ids": [str(doc1_id), str(doc2_id), str(missing_id)]},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["updated"] == 2
    assert str(missing_id) in body["not_found"]
    assert isinstance(docs[doc1_id].disabled_at, datetime)
    assert isinstance(docs[doc2_id].disabled_at, datetime)

    res = client.post("/api/v1/documents/batch/enable", json={"document_ids": [str(doc1_id)]})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["updated"] == 1
    assert docs[doc1_id].disabled_at is None

    res = client.post("/api/v1/documents/batch/archive", json={"document_ids": [str(doc2_id)]})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["updated"] == 1
    assert isinstance(docs[doc2_id].archived_at, datetime)

    res = client.post("/api/v1/documents/batch/unarchive", json={"document_ids": [str(doc2_id)]})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["updated"] == 1
    assert docs[doc2_id].archived_at is None


def test_list_documents_defaults_to_active_lifecycle(monkeypatch):  # noqa: ANN001
    from app.api.v1.documents import list_documents
    from app.models.document import Document as DBDocument

    class _DummyQuery:
        def __init__(self) -> None:
            self.filters = []

        def filter(self, *args, **_kwargs):  # noqa: ANN001
            self.filters.extend(args)
            return self

        def order_by(self, *_args, **_kwargs):  # noqa: ANN001
            return self

        def offset(self, *_args, **_kwargs):  # noqa: ANN001
            return self

        def limit(self, *_args, **_kwargs):  # noqa: ANN001
            return self

        def count(self):  # noqa: ANN001
            return 0

        def all(self):  # noqa: ANN001
            return []

    dummy_query = _DummyQuery()

    class _DummyDB:
        def query(self, model):  # noqa: ANN001
            assert model is DBDocument
            return dummy_query

    # Bypass permission enforcement for unit test.
    import app.api.v1.documents as documents_module

    monkeypatch.setattr(documents_module.DatasetService, "ensure_member", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(documents_module.DatasetService, "get_dataset", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(documents_module.DatasetService, "assert_dataset_readable", lambda *_a, **_k: None, raising=True)

    asyncio.run(
        list_documents(
            skip=0,
            limit=20,
            status=None,
            dataset_id=uuid.uuid4(),
            file_type=None,
            owner_id=None,
            q=None,
            order_by="created_at",
            order_dir="desc",
            tenant_id=uuid.uuid4(),
            account_id="acct",
            db=_DummyDB(),  # type: ignore[arg-type]
        )
    )

    assert any("archived_at" in str(f) and "IS NULL" in str(f) for f in dummy_query.filters)
    assert any("disabled_at" in str(f) and "IS NULL" in str(f) for f in dummy_query.filters)
