from collections.abc import Iterator
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models.document import Document
from app.models.index_drift_item import IndexDriftItem
from app.services import document_index_channel_service, document_ingestion, index_audit_service


@pytest.fixture
def audit_db() -> Iterator[Session]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[IndexDriftItem.__table__])
    with Session(engine) as db:
        yield db
    engine.dispose()


def _marker(tenant_id) -> dict:
    return index_audit_service.build_index_drift_marker(
        operation="upsert",
        strictness="strict",
        tenant_id=tenant_id,
        document_id=None,
        chunk_id=None,
        channel="vector",
        reason="provider_failed",
    )


def test_index_audit_persists_supplied_empty_text(audit_db: Session) -> None:
    tenant_id = uuid4()
    item = index_audit_service.record_index_drift_item(
        db=audit_db, dataset_id=None, marker=_marker(tenant_id), reconcile_task_id=""
    )

    assert item.reconcile_task_id == ""
    resolved = index_audit_service.resolve_index_drift_item(
        db=audit_db, tenant_id=tenant_id, item_id=item.id, resolved_by="", resolution_note=""
    )
    audit_db.refresh(item)

    assert resolved is item
    assert item.status == "resolved"
    assert item.resolved_by == ""
    assert item.resolution_note == ""


@pytest.mark.parametrize("field", ["operation", "channel", "strictness", "reason"])
def test_index_audit_exposes_incomplete_internal_markers_before_persistence(audit_db: Session, field: str) -> None:
    marker = _marker(uuid4())
    del marker[field]

    with pytest.raises(KeyError, match=field):
        index_audit_service.record_index_drift_item(db=audit_db, dataset_id=None, marker=marker)

    assert audit_db.query(IndexDriftItem).count() == 0


def test_index_audit_exposes_an_invalid_resolving_actor_without_changing_state(audit_db: Session) -> None:
    tenant_id = uuid4()
    item = index_audit_service.record_index_drift_item(db=audit_db, dataset_id=None, marker=_marker(tenant_id))

    with pytest.raises(AttributeError):
        index_audit_service.resolve_index_drift_item(
            db=audit_db, tenant_id=tenant_id, item_id=item.id, resolved_by=None
        )

    audit_db.refresh(item)
    assert item.status == "open"
    assert item.resolved_at is None


@pytest.mark.parametrize("error,expected", [(None, None), ("", ""), ("  provider error  ", "provider error")])
def test_channel_error_boundary_preserves_absence_and_supplied_text(error: str | None, expected: str | None) -> None:
    assert document_index_channel_service._normalize_channel_error(error) == expected


def test_channel_error_boundary_keeps_the_existing_length_cap() -> None:
    assert document_index_channel_service._normalize_channel_error("e" * 3000) == "e" * 2000


@pytest.mark.parametrize("error", [0, False])
def test_channel_error_boundary_exposes_invalid_internal_types(error) -> None:
    with pytest.raises(AttributeError):
        document_index_channel_service._normalize_channel_error(error)


def test_legacy_channel_does_not_replace_supplied_empty_error_with_stale_metadata() -> None:
    document = Document(status="failed", error_message="", doc_metadata={"error_message": "stale error"})

    status = document_index_channel_service.legacy_document_index_channel_status(
        document, channel="vector", enabled=True
    )

    assert status["status"] == "error"
    assert status["error"] == ""


@pytest.mark.parametrize("pipeline_hash", ["", "pipeline-1"])
def test_duplicate_ingestion_keeps_the_pipeline_identity_value_consistent(pipeline_hash: str) -> None:
    metadata = {}
    document = Document(doc_metadata={})

    document_ingestion._sync_duplicate_document_pipeline_identity(
        document, doc_metadata=metadata, file_sha256="abc", pipeline_hash=pipeline_hash
    )

    assert metadata["pipeline_hash"] == pipeline_hash
    assert metadata["pipeline_execution_identity"]["pipeline_hash"] == pipeline_hash
    assert document.dedup_key == ("abc:pipeline-1" if pipeline_hash else None)
