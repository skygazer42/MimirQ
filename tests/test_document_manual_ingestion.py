from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import BackgroundTasks

from app.api.schemas.document import ManualChunkCreate, ManualDocumentCreate
from app.api.v1 import document_manual


def _manual_request() -> ManualDocumentCreate:
    return ManualDocumentCreate(
        filename="manual.md",
        file_type="md",
        file_size=12,
        chunks=[ManualChunkCreate(content="manual text")],
    )


def test_manual_document_route_delegates_to_ingestion_service(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import document_manual_ingestion

    request = _manual_request()
    background_tasks = BackgroundTasks()
    tenant_id = uuid4()
    account_id = "account-1"
    db = object()
    result = SimpleNamespace(id=uuid4())
    captured: dict[str, object] = {}

    def create_manual_document(**kwargs):
        captured.update(kwargs)
        return result

    monkeypatch.setattr(
        document_manual,
        "_documents_module",
        lambda: pytest.fail("manual route reached the documents facade"),
        raising=False,
    )
    monkeypatch.setattr(document_manual_ingestion, "create_manual_document", create_manual_document)

    assert (
        document_manual.create_document_with_manual_chunks(
            request,
            background_tasks,
            tenant_id=tenant_id,
            account_id=account_id,
            db=db,
        )
        is result
    )
    assert captured == {
        "request": request,
        "background_tasks": background_tasks,
        "db": db,
        "tenant_id": tenant_id,
        "account_id": account_id,
    }


def test_manual_worker_uses_and_closes_its_owned_session(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import document_manual_ingestion

    document = SimpleNamespace(id=uuid4(), tenant_id=uuid4(), dataset_id=uuid4(), status="processing")
    dataset = SimpleNamespace(id=document.dataset_id, dataset_metadata={})
    captured: dict[str, object] = {}

    class Query:
        def filter(self, *_args):
            return self

        def first(self):
            return document

    class DB:
        def __init__(self):
            self.closed = False

        def query(self, _model):
            return Query()

        def close(self):
            self.closed = True

    db = DB()
    monkeypatch.setattr(document_manual_ingestion, "SessionLocal", lambda: db)
    monkeypatch.setattr(document_manual_ingestion.dataset_service, "get_dataset", lambda *_args: dataset)
    monkeypatch.setattr(document_manual_ingestion.dataset_service, "assert_dataset_writable", lambda *_args: None)
    monkeypatch.setattr(
        document_manual_ingestion,
        "_index_manual_document_chunks",
        lambda **kwargs: captured.update(kwargs),
    )

    document_manual_ingestion.process_manual_chunks(
        document_id=document.id,
        tenant_id=document.tenant_id,
        account_id="account-1",
        request_payload=_manual_request().model_dump(mode="json"),
    )

    assert captured["db"] is db
    assert captured["dataset"] is dataset
    assert captured["document"] is document
    assert db.closed is True


def test_cancelled_manual_worker_closes_its_session_without_processing(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import document_manual_ingestion

    document = SimpleNamespace(id=uuid4(), tenant_id=uuid4(), dataset_id=uuid4(), status="cancelled")

    class Query:
        def filter(self, *_args):
            return self

        def first(self):
            return document

    class DB:
        def __init__(self):
            self.closed = False

        def query(self, _model):
            return Query()

        def close(self):
            self.closed = True

    db = DB()
    request_payload = _manual_request().model_dump(mode="json")
    monkeypatch.setattr(document_manual_ingestion, "SessionLocal", lambda: db)
    monkeypatch.setattr(
        document_manual_ingestion,
        "_index_manual_document_chunks",
        lambda **_kwargs: pytest.fail("cancelled manual document was indexed"),
    )

    document_manual_ingestion.process_manual_chunks(
        document_id=document.id,
        tenant_id=document.tenant_id,
        account_id="account-1",
        request_payload=request_payload,
    )

    assert document.status == "cancelled"
    assert db.closed is True
