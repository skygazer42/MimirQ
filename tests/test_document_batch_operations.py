import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.schemas.document import (
    DocumentAccessUpdateRequest,
    DocumentBatchDeleteRequest,
    DocumentBatchLifecycleRequest,
)
from app.api.v1 import document_access
from app.services import document_access_service, document_lifecycle_service


class Query:
    def __init__(self, document):
        self.document = document

    def filter(self, *_args):
        return self

    def first(self):
        return self.document


class DB:
    def __init__(self, document):
        self.document = document
        self.commits = 0

    def query(self, _model):
        return Query(self.document)

    def commit(self):
        self.commits += 1

    def refresh(self, _document):
        pass


def test_batch_lifecycle_applies_state_and_audits_changed_document(monkeypatch: pytest.MonkeyPatch) -> None:
    document = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        dataset_id=uuid4(),
        status="completed",
        disabled_at=None,
        archived_at=None,
    )
    db = DB(document)
    audit = []
    monkeypatch.setattr(document_lifecycle_service.dataset_service, "ensure_member", lambda *_args: None)
    monkeypatch.setattr(
        document_access_service,
        "assert_document_writable_for_lifecycle",
        lambda *_args, **_kwargs: None,
        raising=True,
    )
    monkeypatch.setattr(
        document_lifecycle_service,
        "audit_log_event",
        lambda *_args, **kwargs: audit.append(kwargs),
    )

    result = document_lifecycle_service.apply_batch_lifecycle(
        payload=DocumentBatchLifecycleRequest(document_ids=[document.id]),
        action="disable",
        db=db,
        tenant_id=document.tenant_id,
        account_id="account-1",
    )

    assert result.updated == 1
    assert isinstance(document.disabled_at, datetime)
    assert document.disabled_at.tzinfo is UTC
    assert db.commits == 1
    assert audit[0]["action"] == "document.disable"


def test_batch_delete_calls_lifecycle_owner_and_classifies_per_id_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = uuid4()
    document_ids = [uuid4(), uuid4(), uuid4()]
    deleted = []
    membership_checks = []
    monkeypatch.setattr(document_lifecycle_service.dataset_service, "ensure_member", lambda *_args: None)

    async def delete_one(**kwargs):
        document_id = kwargs["document_id"]
        deleted.append(document_id)
        membership_checks.append(kwargs["enforce_membership"])
        if document_id == document_ids[1]:
            raise HTTPException(status_code=404, detail="missing")
        if document_id == document_ids[2]:
            raise HTTPException(status_code=403, detail="denied")

    monkeypatch.setattr(document_lifecycle_service, "_delete_document_lifecycle", delete_one)
    result = asyncio.run(
        document_lifecycle_service.delete_batch_documents(
            payload=DocumentBatchDeleteRequest(document_ids=document_ids),
            db=object(),
            tenant_id=tenant_id,
            account_id="account-1",
        )
    )

    assert result.deleted == 1
    assert result.not_found == [document_ids[1]]
    assert result.denied == [document_ids[2]]
    assert deleted == document_ids
    assert membership_checks == [True, True, True]


def test_document_access_route_delegates_to_shared_operation(monkeypatch: pytest.MonkeyPatch) -> None:
    document_id = uuid4()
    tenant_id = uuid4()
    payload = DocumentAccessUpdateRequest(mode="all_team_members")
    db = object()
    result = SimpleNamespace(mode="all_team_members")
    captured = {}

    def update_access(**kwargs):
        captured.update(kwargs)
        return result

    monkeypatch.setattr(document_access_service, "update_access", update_access, raising=False)
    assert (
        document_access.put_document_access(
            document_id=document_id,
            payload=payload,
            tenant_id=tenant_id,
            account_id="account-1",
            db=db,
        )
        is result
    )
    assert captured == {
        "document_id": document_id,
        "payload": payload,
        "db": db,
        "tenant_id": tenant_id,
        "account_id": "account-1",
    }
