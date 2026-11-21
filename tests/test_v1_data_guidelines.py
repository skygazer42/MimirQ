import asyncio
import json
import logging
from collections.abc import Iterator
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, event, literal, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.api.schemas.documents import DocumentDuplicateQuery
from app.api.schemas.identity.groups import (
    TenantGroupCreateRequest,
    TenantGroupMembersUpdateRequest,
    TenantGroupUpdateRequest,
)
from app.api.v1.datasets import routes as datasets
from app.api.v1.documents import duplicates as document_duplicates
from app.api.v1.documents import ingestion_runs
from app.api.v1.documents import versions as document_versions
from app.api.v1.identity import groups, scim
from app.infrastructure.database.connection import Base
from app.models.datasets.records import Dataset
from app.models.datasets.scans import DatasetProfileScanRun
from app.models.documents.records import Document, DocumentChunk
from app.models.identity.workspaces import Tenant, TenantGroup, TenantGroupMember, TenantMember
from app.models.knowledge_graph.entities import KgEntity, KgEventEntity, KgRelation, KgSourceEvent
from app.services.datasets.precheck.results import _scan_run_out_from_row
from app.services.identity import groups as tenant_group_service


@compiles(JSONB, "sqlite")
def _compile_jsonb_as_json(_type, _compiler, **_kwargs) -> str:  # noqa: ANN001
    return "JSON"


@pytest.fixture
def data_db() -> Iterator[Session]:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[
            Tenant.__table__,
            TenantMember.__table__,
            TenantGroup.__table__,
            TenantGroupMember.__table__,
            Dataset.__table__,
            Document.__table__,
            DocumentChunk.__table__,
            KgEntity.__table__,
            KgSourceEvent.__table__,
            KgEventEntity.__table__,
            KgRelation.__table__,
        ],
    )
    with Session(engine) as db:
        yield db
    engine.dispose()


def _request() -> Request:
    return Request({"type": "http", "headers": [], "client": ("127.0.0.1", 1)})


@pytest.mark.parametrize("module", [groups, scim], ids=["groups", "scim"])
@pytest.mark.parametrize("operation", ["create", "update", "delete", "add", "remove"])
def test_group_audit_failure_preserves_the_committed_change(data_db, monkeypatch, caplog, module, operation):
    tenant_id = uuid4()
    data_db.add(TenantMember(tenant_id=tenant_id, user_id="reader", role="viewer"))
    data_db.commit()
    group = tenant_group_service.create_group(data_db, tenant_id=tenant_id, name="readers")
    group_id = group.id
    if operation == "remove":
        tenant_group_service.add_members(data_db, tenant_id=tenant_id, group_id=group_id, member_ids=["reader"])
    monkeypatch.setattr(groups, "ensure_tenant_permission", lambda *args, **kwargs: None)
    monkeypatch.setattr(scim.settings, "SCIM_GROUPS_MUTATION_ENABLED", True)
    monkeypatch.setattr(scim.settings, "SCIM_PATCH_GROUP_MEMBERSHIP_ENABLED", True)
    kwargs = {"db": data_db, "tenant_id": tenant_id}

    with caplog.at_level(logging.WARNING):
        if module is groups:
            kwargs["account_id"] = "owner"
            if operation == "create":
                result = groups.create_group(TenantGroupCreateRequest(name="writers"), **kwargs)
                assert result.name == "writers"
            elif operation == "update":
                result = groups.patch_group(group_id, TenantGroupUpdateRequest(name="writers"), **kwargs)
                assert result.name == "writers"
            elif operation == "delete":
                assert groups.delete_group(group_id, **kwargs).status_code == 204
            else:
                update = groups.add_group_members if operation == "add" else groups.remove_group_members
                result = update(group_id, TenantGroupMembersUpdateRequest(member_ids=["reader"]), **kwargs)
                assert result.updated == 1
        else:
            kwargs["actor_id"] = "system:scim"
            if operation == "create":
                result = scim.create_group({"displayName": "writers"}, _request(), **kwargs)
                assert json.loads(result.body)["displayName"] == "writers"
            elif operation == "update":
                result = scim.put_group(group_id, {"displayName": "writers"}, _request(), **kwargs)
                assert json.loads(result.body)["displayName"] == "writers"
            elif operation == "delete":
                assert scim.delete_group(group_id, _request(), **kwargs).status_code == 204
            else:
                result = scim.patch_group_membership(
                    group_id,
                    {
                        "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
                        "Operations": [{"op": operation, "path": "members", "value": [{"value": "reader"}]}],
                    },
                    **kwargs,
                )
                assert json.loads(result.body)["members"] == (
                    [{"value": "reader", "display": "reader"}] if operation == "add" else []
                )

    assert data_db.is_active
    names = [row.name for row in data_db.query(TenantGroup).order_by(TenantGroup.name).all()]
    expected = {"create": ["readers", "writers"], "update": ["writers"], "delete": []}
    assert names == expected.get(operation, ["readers"])
    if operation in {"add", "remove"}:
        assert data_db.query(TenantGroupMember).count() == (1 if operation == "add" else 0)
    assert any(record.exc_info and "audit" in record.message.lower() for record in caplog.records)


@pytest.mark.parametrize("operation", ["create", "deactivate"])
def test_scim_user_audit_failure_does_not_rollback_user_changes(data_db, monkeypatch, caplog, operation):
    tenant_id = uuid4()
    monkeypatch.setattr(scim.settings, "SCIM_USERS_CREATE_ENABLED", True)
    monkeypatch.setattr(scim.settings, "SCIM_USERS_PATCH_ACTIVE_ENABLED", True)
    monkeypatch.setattr(scim.settings, "SCIM_DEPROVISION_REVOKE_GROUP_MEMBERSHIPS_ENABLED", True)
    if operation == "deactivate":
        data_db.add(TenantMember(tenant_id=tenant_id, user_id="reader", role="viewer", is_active=True, is_current=True))
        data_db.add(TenantGroupMember(tenant_id=tenant_id, group_id=uuid4(), user_id="reader"))
        data_db.commit()
    with caplog.at_level(logging.WARNING):
        if operation == "create":
            result = scim.create_user(
                {"userName": "reader", "active": False},
                _request(),
                tenant_id=tenant_id,
                actor_id="system:scim",
                db=data_db,
            )
            assert result.status_code == 201
        else:
            result = scim.patch_user(
                "reader",
                {
                    "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
                    "Operations": [{"op": "replace", "path": "active", "value": False}],
                },
                _request(),
                tenant_id=tenant_id,
                actor_id="system:scim",
                db=data_db,
            )
        assert json.loads(result.body)["active"] is False
    member = data_db.query(TenantMember).one()
    assert member.is_active is False
    assert member.is_current is False
    assert data_db.query(TenantGroupMember).count() == 0
    assert any(record.exc_info and "audit" in record.message.lower() for record in caplog.records)


@pytest.mark.parametrize("module", [groups, scim], ids=["groups", "scim"])
def test_group_primary_commit_failure_is_not_an_audit_degradation(data_db, monkeypatch, module):
    failure = RuntimeError("group primary commit failed")

    def fail_commit(_session):
        raise failure

    event.listen(data_db, "before_commit", fail_commit)
    monkeypatch.setattr(groups, "ensure_tenant_permission", lambda *args, **kwargs: None)
    monkeypatch.setattr(scim.settings, "SCIM_GROUPS_MUTATION_ENABLED", True)
    with pytest.raises(RuntimeError) as raised:
        if module is groups:
            groups.create_group(
                TenantGroupCreateRequest(name="readers"), tenant_id=uuid4(), account_id="owner", db=data_db
            )
        else:
            scim.create_group({"displayName": "readers"}, _request(), tenant_id=uuid4(), actor_id="scim", db=data_db)
    assert raised.value is failure


@pytest.mark.parametrize("phase", ["metadata", "retry"])
def test_replay_stops_when_rollback_fails(data_db, monkeypatch, phase):
    from app.infrastructure.database import connection as database
    from app.services.documents import processing as document_processing_operations

    tenant_id = uuid4()
    documents = [
        Document(
            id=uuid4(),
            tenant_id=tenant_id,
            filename=f"{index}.txt",
            file_type="txt",
            file_size=1,
            file_path="manual://",
            doc_metadata={},
        )
        for index in range(2)
    ]
    data_db.add_all(documents)
    data_db.commit()
    document_ids = [doc.id for doc in documents]
    retries: list[UUID] = []
    failure = RuntimeError("rollback connection lost")

    def fail_rollback():
        raise failure

    async def retry(**kwargs):
        retries.append(kwargs["document_id"])
        raise RuntimeError("retry failed")

    def fail_lookup(_connection, _cursor, statement, _parameters, _context, _many):
        if phase == "metadata" and statement.startswith("SELECT") and "FROM documents" in statement:
            raise RuntimeError("metadata query failed")

    monkeypatch.setattr(database, "SessionLocal", lambda: data_db)
    monkeypatch.setattr(data_db, "rollback", fail_rollback)
    monkeypatch.setattr(document_processing_operations, "retry_document", retry)
    event.listen(data_db.get_bind(), "before_cursor_execute", fail_lookup)
    with pytest.raises(RuntimeError) as raised:
        asyncio.run(
            ingestion_runs._run_replay_retries(
                tenant_id=tenant_id, account_id="owner", new_run_id=uuid4(), doc_ids=document_ids
            )
        )
    assert raised.value is failure
    assert retries == ([] if phase == "metadata" else document_ids[:1])


def test_replay_attachment_does_not_swallow_the_service_rollback_failure(monkeypatch):
    failure = RuntimeError("attachment rollback failed")

    def fail_attachment(*args, **kwargs):
        raise failure

    monkeypatch.setattr(ingestion_runs.ingestion_run_service, "add_document", fail_attachment)
    with pytest.raises(RuntimeError) as raised:
        ingestion_runs._attach_replay_documents(db=object(), tenant_id=uuid4(), run_id=uuid4(), doc_ids=[uuid4()])
    assert raised.value is failure


@pytest.mark.parametrize("omitted", ["total_documents", "last_processed_at"])
def test_dataset_summary_rejects_an_incomplete_query_projection(data_db, omitted):
    columns = {
        "total_documents": 0,
        "pending_documents": 0,
        "processing_documents": 0,
        "failed_documents": 0,
        "quarantined_documents": 0,
        "completed_documents": 0,
        "cancelled_documents": 0,
        "total_chunks": 0,
        "total_size": 0,
        "total_characters": 0,
        "last_processed_at": None,
    }
    row = data_db.execute(
        select(*(literal(value).label(key) for key, value in columns.items() if key != omitted))
    ).one()
    with pytest.raises(AttributeError):
        datasets._dataset_list_summary_from_row(row)


def test_dataset_summary_keeps_a_valid_empty_outer_join_projection(data_db):
    fields = [
        "total_documents",
        "pending_documents",
        "processing_documents",
        "failed_documents",
        "quarantined_documents",
        "completed_documents",
        "cancelled_documents",
        "total_chunks",
        "total_size",
        "total_characters",
        "last_processed_at",
    ]
    row = data_db.execute(select(*(literal(None).label(field) for field in fields))).one()
    summary = datasets._dataset_list_summary_from_row(row)
    assert summary.total_documents == summary.total_chunks == summary.total_size == summary.total_characters == 0
    assert summary.by_status == {}
    assert summary.last_processed_at is None


@pytest.mark.parametrize("field", ["kind", "status", "progress", "config", "summary"])
def test_profile_scan_projection_rejects_null_required_fields(field):
    values = {"kind": "deep", "status": "running", "progress": 0, "config": {}, "summary": {}}
    values[field] = None
    row = DatasetProfileScanRun(id=uuid4(), tenant_id=uuid4(), dataset_id=uuid4(), **values)
    with pytest.raises(ValidationError):
        _scan_run_out_from_row(row)


def test_profile_scan_projection_preserves_empty_strings_and_zero_progress():
    row = DatasetProfileScanRun(
        id=uuid4(), tenant_id=uuid4(), dataset_id=uuid4(), kind="", status="", progress=0, config={}, summary={}
    )
    result = _scan_run_out_from_row(row)
    assert (result.kind, result.status, result.progress, result.config, result.summary) == ("", "", 0, {}, {})


def _seed_versions(db: Session) -> tuple[UUID, UUID, list[UUID]]:
    tenant_id, document_id = uuid4(), uuid4()
    db.add(
        Document(
            id=document_id,
            tenant_id=tenant_id,
            filename="version.txt",
            file_type="txt",
            file_size=3,
            file_path="manual://",
            owner_id="owner",
            status="completed",
            doc_metadata={"pipeline_hash": "old", "active_pipeline_hash": "new"},
        )
    )
    chunks = [
        DocumentChunk(
            id=uuid4(),
            tenant_id=tenant_id,
            document_id=document_id,
            chunk_index=index,
            content=content,
            doc_metadata={"pipeline_hash": version, "doc_pipeline_key": f"{document_id}:{version}", **metadata},
            created_at=datetime(2026, 1, index + 1, tzinfo=timezone.utc),
        )
        for index, (version, content, metadata) in enumerate(
            [
                ("old", "one", {"content_hash": "shared", "content_len": 3}),
                ("old", "two", {}),
                ("new", "three", {"content_hash": "shared", "content_len": 5}),
            ]
        )
    ]
    db.add_all(chunks)
    db.commit()
    return tenant_id, document_id, [chunk.id for chunk in chunks]


def test_sqlite_document_versions_keep_legacy_hashes_and_version_scope(data_db, monkeypatch):
    tenant_id, document_id, chunk_ids = _seed_versions(data_db)
    monkeypatch.setattr(document_versions.dataset_service, "ensure_member", lambda *args: None)
    monkeypatch.setattr(document_versions, "assert_document_readable_for_lifecycle", lambda *args, **kwargs: None)
    key = f"{document_id}:old"
    assert document_versions._load_version_signatures(
        db=data_db, tenant_id=tenant_id, document_id=document_id, target_key=key
    ) == ["shared", f"id:{chunk_ids[1]}"]
    assert (
        document_versions._load_version_chunk_ids(
            db=data_db, tenant_id=tenant_id, document_id=document_id, target_key=key
        )
        == chunk_ids[:2]
    )
    result = document_versions.list_document_versions(document_id, tenant_id=tenant_id, account_id="owner", db=data_db)
    assert [(item["pipeline_hash"], item["chunk_count"], item["active"]) for item in result["items"]] == [
        ("new", 1, True),
        ("old", 2, False),
    ]


def test_version_activation_exposes_invalid_stored_content_lengths(data_db, monkeypatch):
    tenant_id, document_id, _chunk_ids = _seed_versions(data_db)
    chunk = data_db.query(DocumentChunk).filter(DocumentChunk.chunk_index == 0).one()
    chunk.doc_metadata = {**chunk.doc_metadata, "content_len": "corrupt"}
    data_db.commit()
    monkeypatch.setattr(document_versions.dataset_service, "ensure_member", lambda *args: None)
    monkeypatch.setattr(document_versions, "assert_document_writable_for_lifecycle", lambda *args, **kwargs: None)
    with pytest.raises(ValueError):
        document_versions.activate_document_version(
            document_id, "old", tenant_id=tenant_id, account_id="owner", db=data_db
        )
    data_db.rollback()
    assert data_db.get(Document, document_id).doc_metadata["active_pipeline_hash"] == "new"


def test_version_delete_rolls_back_chunks_metadata_and_kg_together(data_db, monkeypatch):
    from app.rag.retrieval.recall import retriever

    tenant_id, document_id, chunk_ids = _seed_versions(data_db)
    event_id = uuid4()
    data_db.add(
        KgSourceEvent(
            id=event_id,
            tenant_id=tenant_id,
            document_id=document_id,
            chunk_id=chunk_ids[0],
            title="event",
            summary="summary",
            content="content",
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
        )
    )
    data_db.commit()

    class Indexer:
        def __init__(self, db):
            self.db = db

        def delete_document_chunk_vectors(self, **kwargs):
            return None

        def delete_event_indexes_for_chunks(self, **kwargs):
            self.db.query(KgSourceEvent).filter(KgSourceEvent.id == event_id).delete(synchronize_session=False)

    failure = RuntimeError("version transaction commit failed")

    def fail_commit(_session):
        if data_db.query(KgSourceEvent).count() == 0:
            raise failure

    monkeypatch.setattr(document_versions, "Indexer", Indexer)
    monkeypatch.setattr(
        retriever, "hybrid_retriever", SimpleNamespace(remove_from_bm25_index_by_metadata_filter=lambda **kwargs: None)
    )
    monkeypatch.setattr(document_versions.dataset_service, "ensure_member", lambda *args: None)
    monkeypatch.setattr(document_versions, "assert_document_writable_for_lifecycle", lambda *args, **kwargs: None)
    event.listen(data_db, "before_commit", fail_commit)
    with pytest.raises(RuntimeError) as raised:
        document_versions.delete_document_version(
            document_id, "old", tenant_id=tenant_id, account_id="owner", db=data_db
        )
    assert raised.value is failure
    assert data_db.query(DocumentChunk).count() == 3
    assert data_db.get(KgSourceEvent, event_id) is not None
    assert data_db.get(Document, document_id).doc_metadata["pipeline_hash"] == "old"


def test_postgres_duplicate_query_failure_does_not_retry_a_scan(data_db, monkeypatch):
    failure = RuntimeError("postgres duplicate query failed")
    monkeypatch.setattr(document_duplicates.dataset_service, "ensure_member", lambda *args: None)
    monkeypatch.setattr(document_duplicates.dataset_service, "get_dataset", lambda *args: object())
    monkeypatch.setattr(document_duplicates.dataset_service, "assert_dataset_readable", lambda *args: None)
    monkeypatch.setattr(document_duplicates, "build_document_read_filter", lambda **kwargs: True)
    monkeypatch.setattr(data_db, "get_bind", lambda: SimpleNamespace(dialect=SimpleNamespace(name="postgresql")))

    def fail_query(**kwargs):
        raise failure

    monkeypatch.setattr(document_duplicates, "_list_document_duplicates_fast_path", fail_query)
    with pytest.raises(RuntimeError) as raised:
        document_duplicates.list_document_duplicates(
            tenant_id=uuid4(), account_id="owner", db=data_db, params=DocumentDuplicateQuery(dataset_id=uuid4())
        )
    assert raised.value is failure
