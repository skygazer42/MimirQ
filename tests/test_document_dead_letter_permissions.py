from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.api.dependencies.auth import get_current_account_id
from app.api.dependencies.tenant import get_tenant_id
from app.api.v1.document_dead_letters import router
from app.core.database import Base, get_db
from app.models.dataset import Dataset, DatasetPermission, DatasetPermissionEnum
from app.models.document import Document, DocumentPermission
from app.models.group_permissions import DatasetGroupPermission, DocumentGroupPermission
from app.models.ingest_dead_letter import IngestDeadLetter
from app.models.tenant import Tenant, TenantMember
from app.models.tenant_group import TenantGroup, TenantGroupMember


@compiles(JSONB, "sqlite")
def _compile_jsonb_as_json(_type, _compiler, **_kwargs) -> str:  # noqa: ANN001
    return "JSON"


@pytest.fixture
def dead_letter_db() -> Iterator[tuple[Session, SimpleNamespace]]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    tables = [
        Tenant.__table__,
        TenantMember.__table__,
        TenantGroup.__table__,
        TenantGroupMember.__table__,
        Dataset.__table__,
        DatasetPermission.__table__,
        DatasetGroupPermission.__table__,
        Document.__table__,
        DocumentPermission.__table__,
        DocumentGroupPermission.__table__,
        IngestDeadLetter.__table__,
    ]
    Base.metadata.create_all(engine, tables=tables)

    db = Session(engine)
    tenant_id = uuid4()
    account_id = "reader"
    readable_dataset_id = uuid4()
    hidden_dataset_id = uuid4()
    readable_doc_id = uuid4()
    hidden_dataset_doc_id = uuid4()
    hidden_doc_acl_id = uuid4()
    unassigned_doc_id = uuid4()
    now = datetime(2026, 7, 26, 9, 0, tzinfo=UTC)

    db.add_all(
        [
            Tenant(id=tenant_id, name="tenant"),
            TenantMember(tenant_id=tenant_id, user_id=account_id, role="viewer", is_active=True, is_current=True),
            Dataset(
                id=readable_dataset_id,
                tenant_id=tenant_id,
                name="readable",
                permission=DatasetPermissionEnum.PARTIAL_MEMBERS,
                owner_id="dataset-owner",
            ),
            Dataset(
                id=hidden_dataset_id,
                tenant_id=tenant_id,
                name="hidden",
                permission=DatasetPermissionEnum.PARTIAL_MEMBERS,
                owner_id="dataset-owner",
            ),
            DatasetPermission(tenant_id=tenant_id, dataset_id=readable_dataset_id, account_id=account_id),
            Document(
                id=readable_doc_id,
                tenant_id=tenant_id,
                dataset_id=readable_dataset_id,
                filename="readable.pdf",
                file_type="pdf",
                file_size=10,
                file_path="/tmp/readable.pdf",
                owner_id="other-user",
                access_mode="inherit",
                status="failed",
                doc_metadata={},
            ),
            Document(
                id=hidden_dataset_doc_id,
                tenant_id=tenant_id,
                dataset_id=hidden_dataset_id,
                filename="hidden-dataset.pdf",
                file_type="pdf",
                file_size=10,
                file_path="/tmp/hidden-dataset.pdf",
                owner_id="other-user",
                access_mode="inherit",
                status="failed",
                doc_metadata={},
            ),
            Document(
                id=hidden_doc_acl_id,
                tenant_id=tenant_id,
                dataset_id=readable_dataset_id,
                filename="hidden-doc-acl.pdf",
                file_type="pdf",
                file_size=10,
                file_path="/tmp/hidden-doc-acl.pdf",
                owner_id="other-user",
                access_mode="only_me",
                status="failed",
                doc_metadata={},
            ),
            Document(
                id=unassigned_doc_id,
                tenant_id=tenant_id,
                dataset_id=None,
                filename="unassigned.txt",
                file_type="txt",
                file_size=10,
                file_path="/tmp/unassigned.txt",
                owner_id=account_id,
                access_mode="inherit",
                status="failed",
                doc_metadata={},
            ),
        ]
    )

    def _dead_letter(
        *,
        offset_minutes: int,
        dataset_id,
        document_id,
        code: str,
    ) -> IngestDeadLetter:
        stamp = now + timedelta(minutes=offset_minutes)
        return IngestDeadLetter(
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            document_id=document_id,
            status="open",
            failed_stage="chunking",
            error_code=code,
            error_message=code,
            original_payload={},
            producer_service="document_processor",
            schema_version="v1",
            first_failed_at=stamp,
            last_attempt_at=stamp,
            created_at=stamp,
            updated_at=stamp,
        )

    db.add_all(
        [
            _dead_letter(offset_minutes=50, dataset_id=hidden_dataset_id, document_id=None, code="hidden-dataset"),
            _dead_letter(offset_minutes=40, dataset_id=hidden_dataset_id, document_id=hidden_dataset_doc_id, code="hidden-document"),
            _dead_letter(offset_minutes=30, dataset_id=readable_dataset_id, document_id=hidden_doc_acl_id, code="hidden-doc-acl"),
            _dead_letter(offset_minutes=20, dataset_id=None, document_id=None, code="no-scope"),
            _dead_letter(offset_minutes=10, dataset_id=readable_dataset_id, document_id=None, code="readable-dataset"),
            _dead_letter(offset_minutes=5, dataset_id=readable_dataset_id, document_id=readable_doc_id, code="readable-document"),
            _dead_letter(offset_minutes=0, dataset_id=None, document_id=unassigned_doc_id, code="unassigned-document"),
        ]
    )
    db.commit()

    ctx = SimpleNamespace(
        tenant_id=tenant_id,
        account_id=account_id,
        readable_dataset_id=readable_dataset_id,
        hidden_dataset_id=hidden_dataset_id,
        unassigned_doc_id=unassigned_doc_id,
    )
    try:
        yield db, ctx
    finally:
        db.close()
        engine.dispose()


@pytest.fixture
def dead_letter_client(dead_letter_db: tuple[Session, SimpleNamespace]) -> Iterator[tuple[TestClient, Session, SimpleNamespace]]:
    db, ctx = dead_letter_db

    app = FastAPI()
    app.include_router(router, prefix="/api/v1/documents")
    app.dependency_overrides[get_current_account_id] = lambda: ctx.account_id
    app.dependency_overrides[get_tenant_id] = lambda: ctx.tenant_id

    def _override_get_db() -> Iterator[Session]:
        yield db

    app.dependency_overrides[get_db] = _override_get_db

    with TestClient(app) as client:
        yield client, db, ctx


def test_dead_letter_list_filters_acl_before_pagination(dead_letter_client: tuple[TestClient, Session, SimpleNamespace]) -> None:
    client, _db, ctx = dead_letter_client

    response = client.get("/api/v1/documents/dead-letters?limit=2")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["total"] == 3
    assert [item["error_code"] for item in payload["items"]] == [
        "readable-dataset",
        "readable-document",
    ]

    response = client.get("/api/v1/documents/dead-letters?skip=2&limit=2")

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["total"] == 3
    assert [item["error_code"] for item in payload["items"]] == ["unassigned-document"]

    response = client.get(f"/api/v1/documents/dead-letters?dataset_id={ctx.hidden_dataset_id}")
    assert response.status_code == 403, response.text

    response = client.get(f"/api/v1/documents/dead-letters?dataset_id={ctx.readable_dataset_id}")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["total"] == 2
    assert [item["error_code"] for item in payload["items"]] == [
        "readable-dataset",
        "readable-document",
    ]

    response = client.get(f"/api/v1/documents/dead-letters?document_id={ctx.unassigned_doc_id}")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["error_code"] == "unassigned-document"


def test_dead_letter_replay_uses_lifecycle_write_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.api.v1.document_dead_letters as document_dead_letters
    import app.api.v1.document_processing as document_processing
    from app.models.document import Document as DBDocument

    tenant_id = uuid4()
    document_id = uuid4()
    dead_letter = IngestDeadLetter(id=uuid4(), tenant_id=tenant_id, document_id=document_id, status="open")
    document = DBDocument(
        id=document_id,
        tenant_id=tenant_id,
        dataset_id=None,
        filename="unassigned.txt",
        file_type="txt",
        file_size=1,
        file_path="/tmp/unassigned.txt",
        owner_id="other-user",
        status="failed",
    )

    class _Query:
        def __init__(self, item):  # noqa: ANN001
            self.item = item

        def filter(self, *_args):  # noqa: ANN002
            return self

        def first(self):  # noqa: ANN201
            return self.item

    class _DB:
        def query(self, model):  # noqa: ANN001
            if model is IngestDeadLetter:
                return _Query(dead_letter)
            if model is DBDocument:
                return _Query(document)
            return _Query(None)

    called = {"lifecycle": 0}

    def _deny_lifecycle(*_args, **_kwargs):  # noqa: ANN001
        called["lifecycle"] += 1
        raise HTTPException(status_code=403, detail="No permission to manage unassigned documents")

    async def _unexpected_retry(**_kwargs):  # noqa: ANN001
        raise AssertionError("retry_document_processing should not run when lifecycle gate denies replay")

    monkeypatch.setattr(document_dead_letters.DatasetService, "ensure_member", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(
        document_dead_letters,
        "assert_document_writable_for_lifecycle",
        _deny_lifecycle,
        raising=True,
    )
    monkeypatch.setattr(document_processing, "retry_document_processing", _unexpected_retry, raising=True)

    with pytest.raises(HTTPException) as exc:
        import asyncio

        asyncio.run(
            document_dead_letters.replay_ingest_dead_letter(
                dead_letter.id,
                background_tasks=object(),
                tenant_id=tenant_id,
                account_id="viewer",
                db=_DB(),
            )
        )

    assert exc.value.status_code == 403
    assert called["lifecycle"] == 1
