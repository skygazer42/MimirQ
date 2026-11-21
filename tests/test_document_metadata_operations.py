from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.schemas.documents.document import (
    DocumentPipelineOptions,
    DocumentPipelinePatchRequest,
    DocumentUserMetadataPatchRequest,
)
from app.api.schemas.documents.qa import DocumentQAGenerateRequest
from app.services.documents import metadata_operations as operations
from app.services.documents import qa as document_qa_service


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
        self.rollbacks = 0
        self.refreshed = []

    def query(self, _model):
        return Query(self.document)

    def commit(self):
        self.commits += 1

    def refresh(self, document):
        self.refreshed.append(document)

    def rollback(self):
        self.rollbacks += 1


@pytest.fixture
def document(monkeypatch):
    row = SimpleNamespace(
        id=uuid4(),
        tenant_id=uuid4(),
        dataset_id=None,
        owner_id="owner",
        access_mode="only_me",
        status="completed",
        filename="source.txt",
        doc_metadata={
            "pipeline": {"chunk_size": 400, "chunk_overlap": 40, "index": {"chunk_vector_enabled": True}},
            "user": {"tags": ["old"], "notes": "old note", "remove_me": "value"},
        },
    )
    monkeypatch.setattr(operations, "assert_document_writable_for_lifecycle", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(operations, "audit_log_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        document_qa_service, "assert_document_writable_for_lifecycle", lambda *_args, **_kwargs: None, raising=False
    )
    monkeypatch.setattr(document_qa_service, "audit_log_event", lambda *_args, **_kwargs: None, raising=False)
    return row, DB(row)


def test_pipeline_patch_applies_only_explicit_fields_and_replace_starts_empty(document):
    row, db = document
    operations.patch_pipeline(
        document_id=row.id,
        payload=DocumentPipelinePatchRequest(patch=DocumentPipelineOptions(chunk_size=512)),
        db=db,
        tenant_id=row.tenant_id,
        account_id="owner",
    )
    assert row.doc_metadata["pipeline"]["chunk_size"] == 512
    assert row.doc_metadata["pipeline"]["chunk_overlap"] == 40
    assert row.doc_metadata["pipeline"]["index"]["chunk_vector_enabled"] is True

    operations.patch_pipeline(
        document_id=row.id,
        payload=DocumentPipelinePatchRequest(
            patch=DocumentPipelineOptions(chunk_size=640),
            replace=True,
        ),
        db=db,
        tenant_id=row.tenant_id,
        account_id="owner",
    )
    assert row.doc_metadata["pipeline"]["chunk_size"] == 640
    assert "chunk_overlap" not in row.doc_metadata["pipeline"]


def test_user_metadata_patch_preserves_null_delete_tag_normalization_and_replace(document):
    row, db = document
    operations.patch_user_metadata(
        document_id=row.id,
        payload=DocumentUserMetadataPatchRequest(
            patch={"remove_me": None, "tags": [" A ", "a", "B"], "notes": " updated "}
        ),
        db=db,
        tenant_id=row.tenant_id,
        account_id="owner",
    )
    assert row.doc_metadata["user"] == {"tags": ["A", "B"], "notes": "updated"}

    operations.patch_user_metadata(
        document_id=row.id,
        payload=DocumentUserMetadataPatchRequest(patch={"tags": " one, TWO,one "}, replace=True),
        db=db,
        tenant_id=row.tenant_id,
        account_id="owner",
    )
    assert row.doc_metadata["user"] == {"tags": ["one", "TWO"]}


def test_pipeline_patch_keeps_committed_change_when_audit_commit_fails(document, monkeypatch, caplog):
    row, db = document

    def fail_audit(*_args, **_kwargs):
        raise RuntimeError("audit unavailable")

    monkeypatch.setattr(operations, "audit_log_event", fail_audit)
    with caplog.at_level("WARNING"):
        result = operations.patch_pipeline(
            document_id=row.id,
            payload=DocumentPipelinePatchRequest(patch=DocumentPipelineOptions(chunk_size=512)),
            db=db,
            tenant_id=row.tenant_id,
            account_id="owner",
        )

    assert result is row
    assert row.doc_metadata["pipeline"]["chunk_size"] == 512
    assert db.commits == 1
    assert db.rollbacks == 1
    assert "audit" in caplog.text.lower()


@pytest.mark.parametrize("status", ["pending", "processing"])
def test_pipeline_patch_rejects_inflight_document(document, monkeypatch, status):
    row, db = document
    row.status = status
    monkeypatch.setattr(operations, "is_reprocessable_pending_document", lambda _document: False)

    with pytest.raises(HTTPException) as caught:
        operations.patch_pipeline(
            document_id=row.id,
            payload=DocumentPipelinePatchRequest(patch=DocumentPipelineOptions(chunk_size=512)),
            db=db,
            tenant_id=row.tenant_id,
            account_id="owner",
        )

    assert caught.value.status_code == 409
    assert row.doc_metadata["pipeline"]["chunk_size"] == 400


@pytest.mark.parametrize("status", ["pending", "processing"])
def test_qa_rejects_inflight_document_before_generation(document, monkeypatch, status):
    row, db = document
    row.status = status
    monkeypatch.setattr(
        document_qa_service,
        "generate_and_index_document_qa",
        lambda *_args, **_kwargs: pytest.fail("must not generate"),
    )
    with pytest.raises(HTTPException) as caught:
        document_qa_service.generate_document_qa(
            document_id=row.id,
            payload=DocumentQAGenerateRequest(num_pairs=3),
            db=db,
            tenant_id=row.tenant_id,
            account_id="owner",
        )
    assert caught.value.status_code == 409


def test_qa_passes_authorized_document_to_existing_qa_service(document, monkeypatch):
    row, db = document
    captured = []
    monkeypatch.setattr(
        document_qa_service,
        "generate_and_index_document_qa",
        lambda *_args, **kwargs: (
            captured.append(kwargs) or SimpleNamespace(mode="extract", deleted=0, created=1, chunk_ids=[], preview=[])
        ),
    )
    result = document_qa_service.generate_document_qa(
        document_id=row.id,
        payload=DocumentQAGenerateRequest(num_pairs=3),
        db=db,
        tenant_id=row.tenant_id,
        account_id="owner",
    )
    assert result.document_id == row.id
    assert captured[0]["document"] is row
    assert captured[0]["num_pairs"] == 3
