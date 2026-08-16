from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import UniqueConstraint
from sqlalchemy.exc import IntegrityError

from app.models.ingestion_run import IngestionRunDocument
from app.services.ingestion_run_service import IngestionRunService


class _QueryStub:
    def __init__(
        self,
        *,
        kind: str,
        result,
        events: list[str],  # noqa: ANN001
        first_exc: Exception | None = None,
        all_exc: Exception | None = None,
    ) -> None:
        self.kind = kind
        self._result = result
        self._events = events
        self._first_exc = first_exc
        self._all_exc = all_exc
        self.locked = False
        self._events.append(f"query:{kind}")

    def filter(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        return self

    def order_by(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        self._events.append(f"order:{self.kind}")
        return self

    def with_for_update(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        self.locked = True
        self._events.append(f"lock:{self.kind}")
        return self

    def first(self):  # noqa: ANN201
        self._events.append(f"first:{self.kind}")
        if self._first_exc is not None:
            raise self._first_exc
        if isinstance(self._result, list):
            return self._result[0] if self._result else None
        return self._result

    def all(self):  # noqa: ANN201
        self._events.append(f"all:{self.kind}")
        if self._all_exc is not None:
            raise self._all_exc
        if self._result is None:
            return []
        if isinstance(self._result, list):
            return list(self._result)
        return [self._result]


class _CommitDiag:
    constraint_name = "uq_ingestion_run_documents_tenant_run_document"


class _CommitOrigError(Exception):
    def __init__(self) -> None:
        super().__init__(_CommitDiag.constraint_name)
        self.diag = _CommitDiag()


class _ServiceDB:
    def __init__(
        self,
        *,
        run,
        document_query_results=None,  # noqa: ANN001
        commit_exc: Exception | None = None,
        run_first_exc: Exception | None = None,
    ) -> None:
        self.run = run
        self.document_query_results = list(document_query_results or [])
        self.commit_exc = commit_exc
        self.run_first_exc = run_first_exc
        self.events: list[str] = []
        self.run_queries: list[_QueryStub] = []
        self.document_queries: list[_QueryStub] = []
        self.added: list[object] = []
        self.commit_calls = 0
        self.rollback_calls = 0

    def add(self, obj) -> None:  # noqa: ANN001
        self.added.append(obj)

    def query(self, model):  # noqa: ANN001, ANN201
        class_ = getattr(model, "class_", None)
        if class_ is not None:
            model = class_
        name = getattr(model, "__name__", "")
        if name == "IngestionRun":
            query = _QueryStub(
                kind="run",
                result=self.run,
                events=self.events,
                first_exc=self.run_first_exc,
            )
            self.run_queries.append(query)
            return query
        result = self.document_query_results.pop(0) if self.document_query_results else None
        query = _QueryStub(kind="document", result=result, events=self.events)
        self.document_queries.append(query)
        return query

    def commit(self) -> None:
        self.commit_calls += 1
        if self.commit_exc is not None:
            raise self.commit_exc

    def rollback(self) -> None:
        self.rollback_calls += 1

    def refresh(self, _obj) -> None:  # noqa: ANN001
        return None


def test_ingestion_run_document_model_enforces_unique_run_document_attachment() -> None:
    constraints = {
        constraint.name: tuple(column.name for column in constraint.columns)
        for constraint in IngestionRunDocument.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }

    assert constraints["uq_ingestion_run_documents_tenant_run_document"] == (
        "tenant_id",
        "run_id",
        "document_id",
    )


def test_add_document_locks_run_row_before_mutating_stats() -> None:
    tenant_id = uuid4()
    run_id = uuid4()
    document_id = uuid4()
    run = SimpleNamespace(
        id=run_id,
        tenant_id=tenant_id,
        kind="upload",
        status="running",
        stats={},
        started_at=datetime.now(timezone.utc),
        finished_at=None,
    )
    db = _ServiceDB(run=run, document_query_results=[None])

    IngestionRunService.add_document(
        db,
        tenant_id=tenant_id,
        run_id=run_id,
        document_id=document_id,
        source_ref="source.txt",
        initial_status="created",
        doc_meta={"pipeline_hash": "pipe-1"},
    )

    assert db.run_queries
    assert db.run_queries[0].locked is True
    assert run.stats["total_documents"] == 1
    assert run.stats["status_counts"]["created"] == 1


def test_add_document_commits_early_when_attachment_already_exists() -> None:
    tenant_id = uuid4()
    run = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        kind="upload",
        status="running",
        stats={"total_documents": 2, "status_counts": {"created": 2}},
        started_at=datetime.now(timezone.utc),
        finished_at=None,
    )
    existing = SimpleNamespace(run_id=run.id, document_id=uuid4(), status="created")
    db = _ServiceDB(run=run, document_query_results=[existing])

    IngestionRunService.add_document(
        db,
        tenant_id=tenant_id,
        run_id=run.id,
        document_id=existing.document_id,
        source_ref="source.txt",
        initial_status="created",
    )

    assert db.commit_calls == 1
    assert db.rollback_calls == 0
    assert db.added == []
    assert run.stats["total_documents"] == 2


def test_add_document_rolls_back_when_initial_run_lock_fails() -> None:
    db = _ServiceDB(run=None, run_first_exc=RuntimeError("lock failed"))

    IngestionRunService.add_document(
        db,
        tenant_id=uuid4(),
        run_id=uuid4(),
        document_id=uuid4(),
        source_ref="source.txt",
        initial_status="created",
    )

    assert db.commit_calls == 0
    assert db.rollback_calls == 1
    assert db.document_queries == []


def test_add_document_rolls_back_duplicate_attachment_conflicts() -> None:
    tenant_id = uuid4()
    run = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        kind="upload",
        status="running",
        stats={},
        started_at=datetime.now(timezone.utc),
        finished_at=None,
    )
    db = _ServiceDB(
        run=run,
        document_query_results=[None],
        commit_exc=IntegrityError("insert", {}, _CommitOrigError()),
    )

    IngestionRunService.add_document(
        db,
        tenant_id=tenant_id,
        run_id=run.id,
        document_id=uuid4(),
        source_ref="source.txt",
        initial_status="created",
    )

    assert db.rollback_calls == 1


def test_add_document_waits_for_expected_documents_before_finalizing() -> None:
    tenant_id = uuid4()
    run = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        kind="upload",
        status="running",
        config={"expected_documents": 2},
        stats={},
        started_at=datetime.now(timezone.utc),
        finished_at=None,
    )
    db = _ServiceDB(run=run, document_query_results=[None, None])

    IngestionRunService.add_document(
        db,
        tenant_id=tenant_id,
        run_id=run.id,
        document_id=uuid4(),
        source_ref="first.txt",
        initial_status="completed",
    )

    assert run.status == "running"
    assert run.finished_at is None
    assert run.stats["progress"] == 50
    assert run.stats["status_counts"]["completed"] == 1

    IngestionRunService.add_document(
        db,
        tenant_id=tenant_id,
        run_id=run.id,
        document_id=uuid4(),
        source_ref="second.txt",
        initial_status="completed",
    )

    assert run.status == "completed"
    assert run.finished_at is not None
    assert run.stats["progress"] == 100
    assert run.stats["total_documents"] == 2


def test_status_update_waits_for_expected_documents_and_keeps_failure_reasons() -> None:
    tenant_id = uuid4()
    first_doc_id = uuid4()
    second_doc_id = uuid4()
    run = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        dataset_id=None,
        kind="upload",
        status="running",
        config={"expected_documents": 2},
        stats={"total_documents": 2, "status_counts": {"created": 2}},
        started_at=datetime.now(timezone.utc),
        finished_at=None,
    )
    failed_row = SimpleNamespace(run_id=run.id, id=1, status="created")
    completed_row = SimpleNamespace(run_id=run.id, id=2, status="created")

    db_failed = _ServiceDB(run=run, document_query_results=[[failed_row], [failed_row]])
    IngestionRunService.on_document_status_update(
        db_failed,
        tenant_id=tenant_id,
        document_id=first_doc_id,
        new_status="failed",
        error_message="parse_failed: invalid markup",
        doc_meta=None,
    )

    assert run.status == "running"
    assert run.finished_at is None
    assert run.stats["progress"] == 50
    assert run.stats["failure_reasons_top"] == {"parse_failed": 1}
    assert failed_row.status == "failed"

    db_completed = _ServiceDB(run=run, document_query_results=[[completed_row], [completed_row]])
    IngestionRunService.on_document_status_update(
        db_completed,
        tenant_id=tenant_id,
        document_id=second_doc_id,
        new_status="completed",
        error_message=None,
        doc_meta=None,
    )

    assert run.status == "completed"
    assert run.finished_at is not None
    assert run.stats["progress"] == 100
    assert run.stats["status_counts"]["failed"] == 1
    assert run.stats["status_counts"]["completed"] == 1


def test_status_update_keeps_legacy_finalize_when_expected_documents_is_missing() -> None:
    tenant_id = uuid4()
    run = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        dataset_id=None,
        kind="upload",
        status="running",
        config={},
        stats={"total_documents": 1, "status_counts": {"created": 1}},
        started_at=datetime.now(timezone.utc),
        finished_at=None,
    )
    row = SimpleNamespace(run_id=run.id, id=1, status="created")
    db = _ServiceDB(run=run, document_query_results=[[row], [row]])

    IngestionRunService.on_document_status_update(
        db,
        tenant_id=tenant_id,
        document_id=uuid4(),
        new_status="completed",
        error_message=None,
        doc_meta=None,
    )

    assert run.status == "completed"
    assert run.finished_at is not None
    assert run.stats["progress"] == 100


def test_close_intake_reconciles_expected_documents_to_unique_attachments_and_finalizes() -> None:
    tenant_id = uuid4()
    shared_doc_id = uuid4()
    run = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        dataset_id=None,
        kind="upload_batch",
        status="running",
        config={"expected_documents": 2},
        stats={"total_documents": 1, "status_counts": {"completed": 1}},
        started_at=datetime.now(timezone.utc),
        finished_at=None,
    )
    attached = [SimpleNamespace(id=1, run_id=run.id, document_id=shared_doc_id, status="completed")]
    db = _ServiceDB(run=run, document_query_results=[attached])

    IngestionRunService.close_intake(
        db,
        tenant_id=tenant_id,
        run_id=run.id,
        attempted_inputs=2,
        rejected_inputs=0,
        rejection_reasons=[],
    )

    assert db.run_queries
    assert db.run_queries[0].locked is True
    assert run.status == "completed"
    assert run.finished_at is not None
    assert run.config["expected_documents"] == 1
    assert run.stats["total_documents"] == 1
    assert run.stats["status_counts"] == {"completed": 1}
    assert run.stats["attempted_inputs"] == 2
    assert run.stats["rejected_inputs"] == 0
    assert run.stats["progress"] == 100


def test_close_intake_fails_all_rejected_batch_with_zero_attached_documents() -> None:
    tenant_id = uuid4()
    run = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        dataset_id=None,
        kind="upload_batch",
        status="running",
        config={"expected_documents": 2},
        stats={},
        started_at=datetime.now(timezone.utc),
        finished_at=None,
    )
    db = _ServiceDB(run=run, document_query_results=[[]])

    IngestionRunService.close_intake(
        db,
        tenant_id=tenant_id,
        run_id=run.id,
        attempted_inputs=2,
        rejected_inputs=2,
        rejection_reasons=[
            "validation_failed: unsupported extension",
            "validation_failed: empty file",
        ],
    )

    assert run.status == "failed"
    assert run.finished_at is not None
    assert run.config["expected_documents"] == 0
    assert run.stats["total_documents"] == 0
    assert run.stats["attempted_inputs"] == 2
    assert run.stats["rejected_inputs"] == 2
    assert run.stats["rejected_reasons_top"] == {"validation_failed": 2}
    assert run.stats["progress"] == 100


def test_status_update_locks_runs_before_attachment_rows() -> None:
    tenant_id = uuid4()
    run_a_id = uuid4()
    run_b_id = uuid4()
    ordered_run_ids = sorted([run_a_id, run_b_id], key=str)
    runs = {
        run_a_id: SimpleNamespace(
            id=run_a_id,
            tenant_id=tenant_id,
            dataset_id=None,
            kind="upload",
            status="running",
            stats={"total_documents": 1, "status_counts": {"created": 1}},
            started_at=datetime.now(timezone.utc),
            finished_at=None,
        ),
        run_b_id: SimpleNamespace(
            id=run_b_id,
            tenant_id=tenant_id,
            dataset_id=None,
            kind="upload",
            status="running",
            stats={"total_documents": 1, "status_counts": {"created": 1}},
            started_at=datetime.now(timezone.utc),
            finished_at=None,
        ),
    }
    candidate_rows = [
        SimpleNamespace(run_id=run_b_id, id=2, status="created"),
        SimpleNamespace(run_id=run_a_id, id=1, status="created"),
    ]
    locked_rows = [
        SimpleNamespace(run_id=ordered_run_ids[0], id=1, status="created"),
        SimpleNamespace(run_id=ordered_run_ids[1], id=2, status="created"),
    ]

    class _MultiRunDB(_ServiceDB):
        def query(self, model):  # noqa: ANN001, ANN201
            class_ = getattr(model, "class_", None)
            if class_ is not None:
                model = class_
            name = getattr(model, "__name__", "")
            if name == "IngestionRun":
                run = runs[ordered_run_ids[len(self.run_queries)]]
                query = _QueryStub(kind="run", result=run, events=self.events)
                self.run_queries.append(query)
                return query
            result = self.document_query_results.pop(0) if self.document_query_results else None
            query = _QueryStub(kind="document", result=result, events=self.events)
            self.document_queries.append(query)
            return query

    db = _MultiRunDB(run=None, document_query_results=[candidate_rows, locked_rows])

    IngestionRunService.on_document_status_update(
        db,
        tenant_id=tenant_id,
        document_id=uuid4(),
        new_status="completed",
        error_message=None,
        doc_meta=None,
    )

    assert len(db.document_queries) == 2
    assert db.document_queries[0].locked is False
    assert db.document_queries[1].locked is True
    assert [query.locked for query in db.run_queries] == [True, True]
    assert db.events == [
        "query:document",
        "order:document",
        "all:document",
        "query:run",
        "lock:run",
        "first:run",
        "query:run",
        "lock:run",
        "first:run",
        "query:document",
        "order:document",
        "lock:document",
        "all:document",
    ]
    assert locked_rows[0].status == "completed"
    assert locked_rows[1].status == "completed"


def test_status_update_raises_when_required_commit_fails() -> None:
    tenant_id = uuid4()
    run = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        dataset_id=None,
        kind="upload",
        status="running",
        stats={"total_documents": 1, "status_counts": {"created": 1}},
        started_at=datetime.now(timezone.utc),
        finished_at=None,
    )
    row = SimpleNamespace(run_id=run.id, id=1, status="created")
    db = _ServiceDB(run=run, document_query_results=[[row], [row]], commit_exc=RuntimeError("commit failed"))

    with pytest.raises(RuntimeError, match="commit failed"):
        IngestionRunService.on_document_status_update(
            db,
            tenant_id=tenant_id,
            document_id=uuid4(),
            new_status="completed",
            error_message=None,
            doc_meta=None,
            criticality="required",
        )
