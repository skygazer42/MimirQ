from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Column, DateTime, MetaData, Table, Uuid, create_engine
from sqlalchemy.orm import Session

from app.services.evaluation.run_scope import (
    DatasetMismatchError,
    MissingCasesError,
    validate_case_ids_belong_to_dataset,
)
from app.services.observability.periodic_audits import _list_dataset_ids_for_index_audit


def test_periodic_index_audit_reads_real_sqlalchemy_uuid_rows():
    metadata = MetaData()
    datasets = Table(
        "datasets",
        metadata,
        Column("id", Uuid, primary_key=True),
        Column("tenant_id", Uuid, nullable=False),
        Column("created_at", DateTime, nullable=False),
        Column("updated_at", DateTime, nullable=False),
    )
    engine = create_engine("sqlite://")
    metadata.create_all(engine)
    tenant_id, dataset_id, foreign_id = uuid4(), uuid4(), uuid4()
    now = datetime.now(UTC)
    with Session(engine) as db:
        db.execute(
            datasets.insert(),
            [
                {"id": dataset_id, "tenant_id": tenant_id, "created_at": now, "updated_at": now},
                {"id": foreign_id, "tenant_id": uuid4(), "created_at": now, "updated_at": now},
            ],
        )
        db.commit()
        assert _list_dataset_ids_for_index_audit(db, tenant_id=tenant_id, max_datasets=1) == [dataset_id]
    engine.dispose()


def test_regression_scope_uses_typed_uuid_identity_and_keeps_scope_validation():
    class InternalUUID(UUID):
        def __str__(self):
            raise RuntimeError("UUID serialization is not needed for internal comparisons")

    dataset_id = InternalUUID(int=uuid4().int)
    case_id = InternalUUID(int=uuid4().int)
    validate_case_ids_belong_to_dataset(dataset_id=dataset_id, case_ids=[case_id], rows=[(case_id, dataset_id)])
    with pytest.raises(MissingCasesError):
        validate_case_ids_belong_to_dataset(dataset_id=dataset_id, case_ids=[case_id], rows=[])
    with pytest.raises(DatasetMismatchError):
        validate_case_ids_belong_to_dataset(dataset_id=dataset_id, case_ids=[case_id], rows=[(case_id, uuid4())])
    with pytest.raises(DatasetMismatchError):
        validate_case_ids_belong_to_dataset(dataset_id=dataset_id, case_ids=[case_id], rows=[(case_id, None)])


def test_validated_governance_profiles_merge_and_still_reject_cycles():
    from app.api.schemas.pipelines.governance import GovernanceProfileOut, GovernanceProfilePayload
    from app.services.pipelines.profile_resolution import resolve_profile_inheritance

    parent = GovernanceProfileOut(
        key="parent",
        name="Parent",
        payload=GovernanceProfilePayload(
            input_formats=["markdown"],
            pipeline_patch={"enabled": True, "count": 2},
            regex_rules=[{"pattern": "secret", "repl": "hidden"}],
        ),
    )
    child = GovernanceProfileOut(
        key="child",
        name="Child",
        payload=GovernanceProfilePayload(
            extends="parent",
            input_formats=["html", "markdown"],
            pipeline_patch={"count": 3},
        ),
    )
    resolved = resolve_profile_inheritance(child, fetch_by_ref=lambda _ref: parent)
    assert [profile.key for profile in resolved.chain] == ["parent", "child"]
    assert resolved.effective.input_formats == ["markdown", "html"]
    assert resolved.effective.pipeline_patch == {"enabled": True, "count": 3}
    assert resolved.effective.regex_rules == parent.payload.regex_rules
    parent.payload.extends = "child"
    with pytest.raises(ValueError, match="cycle"):
        resolve_profile_inheritance(child, fetch_by_ref={"parent": parent, "child": child}.__getitem__)


def test_dead_letter_stamps_typed_document_and_reuses_open_failure():
    from app.models.documents.records import Document
    from app.services.documents.dead_letters import record_ingest_dead_letter

    class DeadLetterSession:
        current = None

        def query(self, _model):
            return self

        def filter(self, *_clauses):
            return self

        def order_by(self, *_columns):
            return self

        def first(self):
            return self.current

        def add(self, row):
            self.current = row

        def commit(self):
            pass

        def refresh(self, _row):
            pass

    document = Document(
        id=uuid4(),
        tenant_id=uuid4(),
        dataset_id=uuid4(),
        current_stage="parse",
        filename="source.pdf",
        doc_metadata={"task_id": "task-1", "pipeline_hash": "hash-1"},
        processing_attempts=2,
        next_retry_at=datetime.now(UTC),
    )
    db = DeadLetterSession()
    letter = record_ingest_dead_letter(db, document=document, failed_stage=None, error_message="timeout")
    assert letter.document_id is document.id
    assert letter.tenant_id is document.tenant_id
    assert letter.original_payload["task_id"] == "task-1"
    assert document.processing_attempts == 3
    assert document.failed_stage == "parse"
    assert document.next_retry_at is None
    repeated = record_ingest_dead_letter(db, document=document, failed_stage="parse", error_message="timeout")
    assert repeated is letter
    assert repeated.retry_count == 1
    assert document.processing_attempts == 4
