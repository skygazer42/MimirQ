import asyncio
import threading
from contextlib import contextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import BackgroundTasks

from app.api.schemas.sources.connectors import ConnectorValidateRequest
from app.api.v1.connectors import validation as connectors_validation
from app.api.v1.documents import dead_letters as document_dead_letters
from app.api.v1.system import observability, rtbf
from app.services.documents import processing as document_processing_operations
from app.services.indexing import audit as index_audit_service
from app.services.retention import rtbf as rtbf_cascade


def _session_factory(monkeypatch, module, loop_thread):
    opened, closed = [], []

    @contextmanager
    def factory():
        assert threading.get_ident() != loop_thread
        session = SimpleNamespace(owner_thread=threading.get_ident(), commit=lambda: None, rollback=lambda: None)
        opened.append(session)
        try:
            yield session
        finally:
            closed.append(session)

    monkeypatch.setattr(module, "SessionLocal", factory, raising=False)
    return opened, closed


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["queue", "slo", "reconcile", "reconcile_job"])
async def test_observability_database_work_uses_owned_workers_and_queue_keeps_the_loop(monkeypatch, operation):
    from app.services.observability import slo as slo_snapshot_service
    from app.services.observability import task_queue as task_queue_observability_service
    from app.tasks import queue

    loop, loop_thread = asyncio.get_running_loop(), threading.get_ident()
    opened, closed = _session_factory(monkeypatch, observability, loop_thread)
    authorized = []

    def authorize(db, *args):
        assert threading.get_ident() != loop_thread
        assert db is opened[-1]
        authorized.append(True)

    def document_state(*, db, **kwargs):
        assert threading.get_ident() != loop_thread
        assert db is opened[-1]
        return {"document": object(), "already_ready": False, "current_index_readiness": {"ready": False}}

    def audit(db, **kwargs):
        assert threading.get_ident() != loop_thread
        assert db is opened[-1]

    async def snapshot(**kwargs):
        assert asyncio.get_running_loop() is loop
        assert len(opened) == len(closed)
        return SimpleNamespace(enabled=False)

    async def slo(**kwargs):
        assert asyncio.get_running_loop() is loop
        assert len(opened) == len(closed)
        return {"ready": True}

    async def enqueue_reconcile(**kwargs):
        assert asyncio.get_running_loop() is loop
        assert len(opened) == len(closed)
        return {"scope": "document", "status": "enqueued", "task_id": "accepted"}

    async def enqueue_job(**kwargs):
        assert asyncio.get_running_loop() is loop
        assert len(opened) == len(closed)
        return "accepted"

    monkeypatch.setattr(observability, "_ensure_admin", authorize)
    monkeypatch.setattr("app.services.observability.audit_log.audit_log_event", audit)
    monkeypatch.setattr(observability.dataset_service, "get_dataset", lambda db, *args: None)
    monkeypatch.setattr(index_audit_service, "get_index_audit_reconcile_document_state", document_state)
    monkeypatch.setattr(index_audit_service, "enqueue_index_audit_reconcile", enqueue_reconcile)
    monkeypatch.setattr(task_queue_observability_service, "get_task_queue_observability_snapshot", snapshot)
    monkeypatch.setattr(slo_snapshot_service, "build_slo_snapshot", slo)
    monkeypatch.setattr(queue, "enqueue_index_audit_reconcile_job", enqueue_job)
    monkeypatch.setattr(observability.settings, "TASK_QUEUE_ENABLED", True)
    kwargs = {"tenant_id": uuid4(), "account_id": "owner"}
    if operation == "queue":
        result = await observability.get_task_queue_observability_snapshot(
            observability.TaskQueueSnapshotParams(force_refresh=False), **kwargs
        )
        assert result.enabled is False
    elif operation == "slo":
        assert await observability.get_slo_snapshot(**kwargs) == {"ready": True}
    elif operation == "reconcile":
        result = await observability.reconcile_index_audit(
            observability.IndexAuditReconcileRequest(dataset_id=uuid4(), document_id=uuid4()), **kwargs
        )
        assert result["status"] == "enqueued"
        assert result["current_index_readiness"] == {"ready": False}
    else:
        result = await observability.enqueue_index_audit_reconcile_job_endpoint(
            observability.IndexAuditReconcileEnqueueRequest(dataset_id=uuid4(), document_id=uuid4()), **kwargs
        )
        assert result.status == "enqueued"
    assert authorized
    assert opened == closed


@pytest.mark.asyncio
async def test_connector_validation_moves_membership_and_dns_off_loop_but_keeps_async_connectivity(monkeypatch):
    loop, loop_thread = asyncio.get_running_loop(), threading.get_ident()
    opened, closed = _session_factory(monkeypatch, connectors_validation, loop_thread)

    def authorize(db, *args, **kwargs):
        assert threading.get_ident() != loop_thread
        assert db is opened[-1]

    def dns(config):
        assert threading.get_ident() != loop_thread
        return ["203.0.113.12"]

    async def connectivity(**kwargs):
        assert asyncio.get_running_loop() is loop
        assert opened == closed
        assert kwargs["cfg"].host == "db.example.com"
        return {"db_connectivity": {"ok": True}}, []

    monkeypatch.setattr(connectors_validation.dataset_service, "ensure_member", authorize)
    monkeypatch.setattr(connectors_validation, "ensure_tenant_permission", authorize)
    monkeypatch.setattr(connectors_validation, "validate_db_connector_config", dns)
    monkeypatch.setattr(connectors_validation, "_best_effort_connectivity_checks", connectivity)
    response = await connectors_validation.validate_connector_config(
        ConnectorValidateRequest(
            connector_id="mysql_catalog",
            config={"host": "db.example.com", "database": "catalog", "username": "reader", "password": "secret"},
            check_connectivity=True,
        ),
        tenant_id=uuid4(),
        account_id="owner",
    )
    assert response.ok is True
    assert response.checks["egress"]["resolved_addresses"] == ["203.0.113.12"]
    assert response.checks["db_connectivity"]["ok"] is True
    assert "secret" not in str(response.config)
    assert opened == closed


@pytest.mark.asyncio
async def test_dead_letter_replay_prepares_and_marks_in_workers_and_propagates_mark_failure(monkeypatch):
    loop, loop_thread = asyncio.get_running_loop(), threading.get_ident()
    opened, closed = _session_factory(monkeypatch, document_dead_letters, loop_thread)
    tenant_id, document_id, dead_letter_id = uuid4(), uuid4(), uuid4()
    dead_letter = SimpleNamespace(id=dead_letter_id, tenant_id=tenant_id, document_id=document_id, status="open")
    document = SimpleNamespace(id=document_id, tenant_id=tenant_id, status="completed")

    class Query:
        def __init__(self, row):
            self.row = row

        def filter(self, *args):
            return self

        def first(self):
            return self.row

    @contextmanager
    def factory():
        assert threading.get_ident() != loop_thread
        db = SimpleNamespace(
            query=lambda model: Query(dead_letter if model is document_dead_letters.IngestDeadLetter else document)
        )
        opened.append(db)
        try:
            yield db
        finally:
            closed.append(db)

    def authorize(db, *args, **kwargs):
        assert threading.get_ident() != loop_thread
        assert db is opened[-1]

    async def retry(**kwargs):
        assert asyncio.get_running_loop() is loop
        assert opened == closed
        assert kwargs["force"] is True
        return {"status": "pending"}

    failure = RuntimeError("replayed state commit failed")

    def mark(db, **kwargs):
        assert threading.get_ident() != loop_thread
        assert db is opened[-1]
        raise failure

    monkeypatch.setattr(document_dead_letters, "SessionLocal", factory, raising=False)
    monkeypatch.setattr(document_dead_letters.dataset_service, "ensure_member", authorize)
    monkeypatch.setattr(document_dead_letters, "assert_document_writable_for_lifecycle", authorize)
    monkeypatch.setattr(document_dead_letters, "mark_dead_letter_replayed", mark)
    monkeypatch.setattr(document_processing_operations, "retry_document", retry)
    with pytest.raises(RuntimeError) as raised:
        await document_dead_letters.replay_ingest_dead_letter(
            dead_letter_id, BackgroundTasks(), tenant_id=tenant_id, account_id="owner", db=object()
        )
    assert raised.value is failure
    assert opened == closed


@pytest.mark.asyncio
async def test_rtbf_permission_and_candidate_audit_work_use_workers(monkeypatch):
    loop_thread = threading.get_ident()
    opened, closed = _session_factory(monkeypatch, rtbf, loop_thread)
    monkeypatch.setattr(rtbf_cascade, "SessionLocal", rtbf.SessionLocal, raising=False)

    def authorize(db, *args, **kwargs):
        assert threading.get_ident() != loop_thread
        assert db is opened[-1]

    def candidates(db, **kwargs):
        assert threading.get_ident() != loop_thread
        assert db is opened[-1]
        return []

    def audit(db, **kwargs):
        assert threading.get_ident() != loop_thread
        assert db is opened[-1]
        db.commit = lambda: None

    monkeypatch.setattr(rtbf, "ensure_tenant_permission", authorize)
    monkeypatch.setattr(rtbf_cascade, "_list_rtbf_documents", candidates)
    monkeypatch.setattr(rtbf_cascade, "_audit_rtbf_summary", audit)
    result = await rtbf.request_rtbf_cascade(
        rtbf.RTBFRequest(subject_account_id="subject", dry_run=True), tenant_id=uuid4(), account_id="owner", db=object()
    )
    assert result["eligible"] == 0
    assert result["dry_run"] is True
    assert opened == closed


@pytest.mark.asyncio
async def test_document_retry_uses_owned_database_stages_and_keeps_queue_on_the_request_loop(monkeypatch, tmp_path):
    from app.models.documents.records import Document
    from app.services.documents import processing_dispatch as document_processing_dispatch

    loop, loop_thread = asyncio.get_running_loop(), threading.get_ident()
    opened, closed = [], []
    source = tmp_path / "retry.txt"
    source.write_text("retry content", encoding="utf-8")
    document = Document(
        id=uuid4(),
        tenant_id=uuid4(),
        filename="retry.txt",
        file_type="txt",
        file_path=str(source),
        status="failed",
        processing_progress=0,
        processing_attempts=1,
        doc_metadata={"parser_backend": "auto"},
    )

    class Query:
        def filter(self, *args):
            return self

        def first(self):
            return document

    def check_worker(*args, **kwargs):
        assert threading.get_ident() != loop_thread

    @contextmanager
    def factory():
        check_worker()
        db = SimpleNamespace(query=lambda *args: Query(), commit=check_worker, refresh=check_worker)
        opened.append(db)
        try:
            yield db
        finally:
            closed.append(db)

    async def enqueue(**kwargs):
        assert asyncio.get_running_loop() is loop
        assert opened == closed
        assert kwargs["document_id"] == document.id
        return "accepted-retry"

    monkeypatch.setattr(document_processing_operations, "SessionLocal", factory, raising=False)
    monkeypatch.setattr(document_processing_dispatch, "SessionLocal", factory, raising=False)
    monkeypatch.setattr(document_processing_operations.dataset_service, "ensure_member", check_worker)
    monkeypatch.setattr(document_processing_operations, "assert_document_writable_for_lifecycle", check_worker)
    monkeypatch.setattr(document_processing_operations, "reconcile_document_index_channels", check_worker)
    monkeypatch.setattr(document_processing_dispatch, "enqueue_document_processing", enqueue)
    response = await document_processing_operations.retry_document(
        document_id=document.id,
        background_tasks=BackgroundTasks(),
        tenant_id=document.tenant_id,
        account_id="owner",
        db=object(),
    )
    assert response.status == "pending"
    assert document.doc_metadata["task_id"] == "accepted-retry"
    assert opened == closed
