import asyncio
import threading
from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session, sessionmaker

from app.api.schemas.sources.connectors import ConnectorRunOut
from app.infrastructure.database.connection import Base
from app.models.connectors.configs import ConnectorConfig
from app.models.connectors.runs import ConnectorRun, ConnectorRunDocument
from app.services.connectors import configs as connector_config_operations
from app.services.connectors import runs as connector_run_operations
from app.services.connectors import schedules as connector_schedule_operations


@compiles(JSONB, "sqlite")
def _compile_jsonb_as_json(_type, _compiler, **_kwargs):
    return "JSON"


@pytest.fixture
def connector_store(tmp_path, monkeypatch):
    from app.services.runtime import retrieval_limiter as rag_runtime_limiter

    engine = create_engine(
        f"sqlite:///{(tmp_path / 'connectors.sqlite').as_posix()}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(
        engine,
        tables=[ConnectorRun.__table__, ConnectorRunDocument.__table__, ConnectorConfig.__table__],
    )
    sessions = []
    insert_commits = []

    class OwnedSession(Session):
        def __init__(self, **kwargs):
            super().__init__(**kwargs)
            self.test_owner = threading.get_ident()
            self.test_closed = False
            sessions.append(self)

        def close(self):
            assert threading.get_ident() == self.test_owner
            super().close()
            self.test_closed = True

    @event.listens_for(engine, "before_cursor_execute")
    def assert_blocking_io(_conn, _cursor, _statement, _parameters, _context, _executemany):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return
        pytest.fail("connector database I/O must run in an owned worker")

    @event.listens_for(OwnedSession, "after_flush")
    def record_insert(session, _context):
        new_ids = [run.id for run in session.new if isinstance(run, ConnectorRun)]
        session.info.setdefault("inserted_runs", []).extend(new_ids)

    @event.listens_for(OwnedSession, "after_commit")
    def record_committed_runs(session):
        if run_ids := session.info.pop("inserted_runs", []):
            insert_commits.append(tuple(run_ids))

    factory = sessionmaker(bind=engine, class_=OwnedSession, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(rag_runtime_limiter, "SessionLocal", factory)
    monkeypatch.setattr(connector_run_operations.settings, "TASK_QUEUE_ENABLED", True)
    monkeypatch.setattr(connector_run_operations.settings, "URL_INGEST_ENABLED", True)
    monkeypatch.setattr(connector_config_operations.dataset_service, "ensure_member", lambda *_args: None)
    monkeypatch.setattr(
        connector_config_operations.dataset_service,
        "get_dataset",
        lambda _db, _tenant_id, dataset_id: SimpleNamespace(id=dataset_id),
    )
    monkeypatch.setattr(connector_config_operations.dataset_service, "assert_dataset_writable", lambda *_args: None)
    yield SimpleNamespace(factory=factory, insert_commits=insert_commits, sessions=sessions)
    engine.dispose()
    assert all(session.test_closed for session in sessions)


def _seed_config(store, *, tenant_id, dataset_id, schedule=None, last_run_at=None):
    with store.factory() as db:
        config = ConnectorConfig(
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            connector_id="url_batch",
            name="test config",
            config={"urls": ["https://example.com/a"]},
            state={},
            enabled=True,
            schedule_cron=schedule,
            last_run_at=last_run_at,
            last_error="previous_error",
        )
        db.add(config)
        db.commit()
        return config.id


def _seed_pending_run(store, *, tenant_id, dataset_id, connector_id="url_batch"):
    with store.factory() as db:
        run = ConnectorRun(
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            connector_id=connector_id,
            requested_by="member-1",
            status="pending",
            config={},
            stats={},
            task_id="stale-task",
        )
        db.add(run)
        db.commit()
        return connector_run_operations._run_out(run)


@pytest.mark.parametrize("mode", ["none", "exception"])
def test_shared_connector_enqueue_helper_fails_closed_when_queue_handoff_fails(monkeypatch, connector_store, mode):
    store = connector_store
    tenant_id = uuid4()
    run = _seed_pending_run(store, tenant_id=tenant_id, dataset_id=uuid4())
    background_tasks = BackgroundTasks()
    main_thread = threading.get_ident()
    enqueued = []

    async def enqueue(**kwargs):
        assert threading.get_ident() == main_thread
        asyncio.get_running_loop()
        enqueued.append(kwargs["run_id"])
        if mode == "exception":
            raise RuntimeError("queue down")
        return None

    monkeypatch.setattr(connector_run_operations, "enqueue_connector_run", enqueue)
    with store.factory() as request_db:
        with pytest.raises(HTTPException) as caught:
            asyncio.run(
                connector_run_operations.enqueue_or_schedule_run(
                    request_db,
                    background_tasks=background_tasks,
                    run=run,
                    tenant_id=tenant_id,
                    requested_by="member-1",
                )
            )

    assert caught.value.status_code == 503
    assert caught.value.detail == connector_run_operations.CONNECTOR_QUEUE_UNAVAILABLE_DETAIL
    with store.factory() as db:
        persisted = db.get(ConnectorRun, run.id)
        assert persisted.task_id is None
        assert persisted.status == "failed"
        assert persisted.error_message == "connector_queue_handoff_failed"
        assert persisted.finished_at is not None
        assert db.query(ConnectorRun).count() == 1
    assert enqueued == [run.id]
    assert store.insert_commits == [(run.id,)]
    assert background_tasks.tasks == []


def test_shared_connector_enqueue_helper_rejects_unsupported_connector_before_handoff(monkeypatch, connector_store):
    store = connector_store
    tenant_id = uuid4()
    run = _seed_pending_run(store, tenant_id=tenant_id, dataset_id=uuid4(), connector_id="unknown")
    enqueued = []

    async def unexpected_enqueue(**kwargs):
        enqueued.append(kwargs)
        return "task-id"

    monkeypatch.setattr(connector_run_operations, "enqueue_connector_run", unexpected_enqueue)
    with store.factory() as request_db:
        with pytest.raises(HTTPException) as caught:
            asyncio.run(
                connector_run_operations.enqueue_or_schedule_run(
                    request_db,
                    background_tasks=BackgroundTasks(),
                    run=run,
                    tenant_id=tenant_id,
                    requested_by="member-1",
                )
            )

    assert caught.value.status_code == 400
    assert enqueued == []
    with store.factory() as db:
        persisted = db.get(ConnectorRun, run.id)
        assert persisted.status == "failed"
        assert persisted.error_message == "unsupported_connector_id"


def test_run_connector_config_uses_shared_enqueue_helper(monkeypatch, connector_store):
    from app.api.v1.connectors import configs as connectors_configs

    store = connector_store
    tenant_id, dataset_id = uuid4(), uuid4()
    config_id = _seed_config(store, tenant_id=tenant_id, dataset_id=dataset_id)
    queued = []
    background_tasks = BackgroundTasks()
    main_thread = threading.get_ident()

    def committed_run_count():
        with store.factory() as db:
            return db.query(ConnectorRun).count()

    async def enqueue(db, *, background_tasks, run, tenant_id, requested_by):
        assert threading.get_ident() == main_thread
        assert isinstance(run, ConnectorRunOut)
        assert await asyncio.to_thread(committed_run_count) == 1
        queued.append((db, background_tasks, run, tenant_id, requested_by))
        return run.model_copy(update={"task_id": "shared-task"})

    monkeypatch.setattr(connector_config_operations, "enqueue_or_schedule_run", enqueue)
    with store.factory() as request_db:
        result = asyncio.run(
            connectors_configs.run_connector_config(
                config_id=config_id,
                background_tasks=background_tasks,
                tenant_id=tenant_id,
                account_id="member-1",
                db=request_db,
            )
        )
        assert queued[0][0] is request_db

    assert isinstance(result, ConnectorRunOut)
    assert result.task_id == "shared-task"
    assert len(queued) == 1
    assert queued[0][1] is background_tasks
    assert queued[0][3:] == (tenant_id, "member-1")
    assert queued[0][2].stats == {"config_id": str(config_id)}
    assert store.insert_commits == [(result.id,)]
    with store.factory() as db:
        config = db.get(ConnectorConfig, config_id)
        assert config.last_run_at is not None
        assert config.last_error is None
    assert background_tasks.tasks == []


def test_scheduled_config_claim_dedupes_same_window_and_uses_shared_enqueue_helper(monkeypatch, connector_store):
    store = connector_store
    tenant_id, dataset_id = uuid4(), uuid4()
    config_id = _seed_config(store, tenant_id=tenant_id, dataset_id=dataset_id, schedule="@hourly")
    now = datetime(2026, 7, 25, 10, 0)
    barrier = threading.Barrier(2)
    queued = []
    is_due = connector_schedule_operations._is_scheduled_config_due

    def both_read_previous_window(config, *, now):
        due = is_due(config, now=now)
        barrier.wait(timeout=5)
        return due

    async def enqueue(_db, *, background_tasks, run, tenant_id, requested_by):
        assert isinstance(run, ConnectorRunOut)
        queued.append(run.id)
        return run

    monkeypatch.setattr(connector_schedule_operations, "_now", lambda: now)
    monkeypatch.setattr(connector_schedule_operations, "_is_scheduled_config_due", both_read_previous_window)
    monkeypatch.setattr(connector_schedule_operations, "enqueue_or_schedule_run", enqueue)

    async def concurrent_ticks():
        with store.factory() as request_db:
            return await asyncio.gather(
                *[
                    connector_schedule_operations.tick_schedules(
                        background_tasks=BackgroundTasks(),
                        db=request_db,
                        tenant_id=tenant_id,
                        account_id="member-1",
                    )
                    for _ in range(2)
                ]
            )

    results = asyncio.run(concurrent_ticks())
    assert sum(result["enqueued"] for result in results) == 1
    assert sum(result["skipped"] for result in results) == 1
    assert len(queued) == 1
    assert store.insert_commits == [(queued[0],)]
    with store.factory() as db:
        assert db.query(ConnectorRun).count() == 1
        assert db.get(ConnectorConfig, config_id).last_run_at == now


def test_run_connector_config_fails_closed_when_queue_handoff_fails(monkeypatch, connector_store):
    from app.api.v1.connectors import configs as connectors_configs

    store = connector_store
    tenant_id, dataset_id = uuid4(), uuid4()
    previous = datetime(2026, 7, 25, 8, 0)
    config_id = _seed_config(store, tenant_id=tenant_id, dataset_id=dataset_id, last_run_at=previous)

    async def enqueue_none(**_kwargs):
        return None

    monkeypatch.setattr(connector_run_operations, "enqueue_connector_run", enqueue_none)
    background_tasks = BackgroundTasks()
    with store.factory() as request_db:
        with pytest.raises(HTTPException) as caught:
            asyncio.run(
                connectors_configs.run_connector_config(
                    config_id=config_id,
                    background_tasks=background_tasks,
                    tenant_id=tenant_id,
                    account_id="member-1",
                    db=request_db,
                )
            )

    assert caught.value.status_code == 503
    assert caught.value.detail == connector_run_operations.CONNECTOR_QUEUE_UNAVAILABLE_DETAIL
    with store.factory() as db:
        runs = db.query(ConnectorRun).all()
        assert len(runs) == 1
        assert runs[0].status == "failed"
        assert runs[0].task_id is None
        config = db.get(ConnectorConfig, config_id)
        assert config.last_run_at == previous
        assert config.last_error == "connector_queue_handoff_failed"
        assert store.insert_commits == [(runs[0].id,)]
    assert background_tasks.tasks == []


def test_scheduled_config_fails_closed_when_queue_handoff_fails(monkeypatch, connector_store):
    store = connector_store
    tenant_id, dataset_id = uuid4(), uuid4()
    config_id = _seed_config(store, tenant_id=tenant_id, dataset_id=dataset_id, schedule="@hourly")
    now = datetime(2026, 7, 25, 10, 0)

    async def enqueue_none(**_kwargs):
        return None

    monkeypatch.setattr(connector_schedule_operations, "_now", lambda: now)
    monkeypatch.setattr(connector_run_operations, "enqueue_connector_run", enqueue_none)
    background_tasks = BackgroundTasks()
    with store.factory() as request_db:
        with pytest.raises(HTTPException) as caught:
            asyncio.run(
                connector_schedule_operations.tick_schedules(
                    background_tasks=background_tasks,
                    db=request_db,
                    tenant_id=tenant_id,
                    account_id="member-1",
                )
            )

    assert caught.value.status_code == 503
    assert caught.value.detail == connector_run_operations.CONNECTOR_QUEUE_UNAVAILABLE_DETAIL
    with store.factory() as db:
        failed_run = db.query(ConnectorRun).one()
        assert failed_run.status == "failed"
        assert failed_run.task_id is None
        config = db.get(ConnectorConfig, config_id)
        assert config.last_run_at is None
        assert config.last_error == "connector_queue_handoff_failed"

    async def enqueue_success(**_kwargs):
        return "retry-task"

    monkeypatch.setattr(connector_run_operations, "enqueue_connector_run", enqueue_success)
    with store.factory() as request_db:
        retried = asyncio.run(
            connector_schedule_operations.tick_schedules(
                background_tasks=background_tasks,
                db=request_db,
                tenant_id=tenant_id,
                account_id="member-1",
            )
        )
    assert retried == {"enqueued": 1, "skipped": 0}
    with store.factory() as db:
        runs = db.query(ConnectorRun).all()
        assert len(runs) == 2
        assert sorted(run.status for run in runs) == ["failed", "pending"]
        assert [run.task_id for run in runs if run.status == "pending"] == ["retry-task"]
        config = db.get(ConnectorConfig, config_id)
        assert config.last_run_at == now
        assert config.last_error is None
    assert len(store.insert_commits) == 2
    assert all(len(run_ids) == 1 for run_ids in store.insert_commits)
    assert background_tasks.tasks == []


@pytest.mark.parametrize("repeat_phase", ["preparation", "recovery"])
def test_cancelled_schedule_preparation_releases_committed_window_before_retry(
    monkeypatch, connector_store, repeat_phase
):
    store = connector_store
    tenant_id, dataset_id = uuid4(), uuid4()
    config_id = _seed_config(store, tenant_id=tenant_id, dataset_id=dataset_id, schedule="@hourly")
    now = datetime(2026, 7, 25, 10, 0)
    prepared, release_prepare = threading.Event(), threading.Event()
    recovering, release_recovery = threading.Event(), threading.Event()
    prepare = connector_schedule_operations._prepare_scheduled_config
    recover = connector_schedule_operations._recover_scheduled_config
    queue_calls = []

    def committed_prepare(*args, **kwargs):
        result = prepare(*args, **kwargs)
        assert result[0] == "enqueued" and isinstance(result[1], ConnectorRunOut)
        prepared.set()
        assert release_prepare.wait(5)
        return result

    def blocked_recovery(*args, **kwargs):
        recovering.set()
        assert release_recovery.wait(5)
        return recover(*args, **kwargs)

    async def enqueue(**kwargs):
        queue_calls.append(kwargs["run_id"])
        return "retry-task"

    monkeypatch.setattr(connector_schedule_operations, "_now", lambda: now)
    monkeypatch.setattr(connector_schedule_operations, "_prepare_scheduled_config", committed_prepare)
    monkeypatch.setattr(connector_schedule_operations, "_recover_scheduled_config", blocked_recovery)
    monkeypatch.setattr(connector_run_operations, "enqueue_connector_run", enqueue)
    background_tasks = BackgroundTasks()

    async def cancel_committed_preparation():
        with store.factory() as request_db:
            task = asyncio.create_task(
                connector_schedule_operations.tick_schedules(
                    background_tasks=background_tasks,
                    db=request_db,
                    tenant_id=tenant_id,
                    account_id="member-1",
                )
            )
            try:
                assert await asyncio.to_thread(prepared.wait, 5)
                task.cancel()
                await asyncio.sleep(0)
                if repeat_phase == "preparation":
                    task.cancel()
                    await asyncio.sleep(0)
                assert not task.done()
                release_prepare.set()
                assert await asyncio.to_thread(recovering.wait, 5)
                if repeat_phase == "recovery":
                    task.cancel()
                    await asyncio.sleep(0)
                assert not task.done()
            finally:
                release_prepare.set()
                release_recovery.set()
                with pytest.raises(asyncio.CancelledError):
                    await task

    asyncio.run(cancel_committed_preparation())
    assert queue_calls == []
    assert background_tasks.tasks == []
    assert all(session.test_closed for session in store.sessions)
    with store.factory() as db:
        failed_run = db.query(ConnectorRun).one()
        assert failed_run.status == "failed"
        assert failed_run.task_id is None
        assert failed_run.error_message == "connector_request_cancelled_before_handoff"
        assert failed_run.finished_at == now
        config = db.get(ConnectorConfig, config_id)
        assert config.last_run_at is None
        assert config.last_error == "connector_request_cancelled_before_handoff"
        cancelled_run_id = failed_run.id

    monkeypatch.setattr(connector_schedule_operations, "_prepare_scheduled_config", prepare)
    monkeypatch.setattr(connector_schedule_operations, "_recover_scheduled_config", recover)
    with store.factory() as request_db:
        result = asyncio.run(
            connector_schedule_operations.tick_schedules(
                background_tasks=background_tasks,
                db=request_db,
                tenant_id=tenant_id,
                account_id="member-1",
            )
        )
    assert result == {"enqueued": 1, "skipped": 0}
    with store.factory() as db:
        pending_run = db.query(ConnectorRun).filter(ConnectorRun.status == "pending").one()
        assert pending_run.id != cancelled_run_id
        assert pending_run.task_id == "retry-task"
        assert queue_calls == [pending_run.id]
        assert db.query(ConnectorRun).count() == 2
        config = db.get(ConnectorConfig, config_id)
        assert config.last_run_at == now and config.last_error is None


def test_cancelled_connector_prepare_failure_remains_observable_without_losing_cancellation(
    monkeypatch, connector_store, caplog
):
    from app.services.runtime.handoff import prepare_managed_handoff

    store = connector_store
    started, release = threading.Event(), threading.Event()
    recovered = []

    def failing_prepare(_db):
        started.set()
        assert release.wait(5)
        raise RuntimeError("connector preparation failed after cancellation")

    async def cancel_failed_preparation():
        task = asyncio.create_task(
            prepare_managed_handoff(failing_prepare, recover_cancelled=lambda db, result: recovered.append(result))
        )
        try:
            assert await asyncio.to_thread(started.wait, 5)
            task.cancel()
            await asyncio.sleep(0)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
        finally:
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task

    with caplog.at_level("ERROR"):
        asyncio.run(cancel_failed_preparation())
    assert recovered == []
    assert all(session.test_closed for session in store.sessions)
    assert any(
        record.exc_info is not None
        and isinstance(record.exc_info[1], RuntimeError)
        and str(record.exc_info[1]) == "connector preparation failed after cancellation"
        for record in caplog.records
    )


class _QueryStub:
    def __init__(self, value):
        self._value = value

    def filter(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        return self

    def first(self):  # noqa: ANN201
        return self._value


class _ConfigLookupDB:
    def __init__(self, cfg):
        self.cfg = cfg
        self.added: list[object] = []
        self.commits = 0
        self.refreshed: list[object] = []

    def query(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN201
        return _QueryStub(self.cfg)

    def add(self, obj) -> None:  # noqa: ANN001
        if getattr(obj, "id", None) is None:
            obj.id = uuid4()
        self.added.append(obj)

    def commit(self) -> None:
        self.commits += 1

    def refresh(self, obj) -> None:  # noqa: ANN001
        self.refreshed.append(obj)

    def close(self) -> None:
        return None


def test_worker_marks_unsupported_connector_run_failed(monkeypatch) -> None:  # noqa: ANN001
    import app.tasks.jobs as jobs

    tenant_id = uuid4()
    run_id = uuid4()
    run = SimpleNamespace(
        id=run_id,
        tenant_id=tenant_id,
        connector_id="unknown",
        status="pending",
        error_message=None,
        finished_at=None,
    )
    db = _ConfigLookupDB(run)

    async def _unsupported(**_kwargs):  # noqa: ANN003, ANN202
        return False

    async def _tenant_acquire(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        return None

    async def _acquire(_redis, **_kwargs):  # noqa: ANN001, ANN202
        return True

    monkeypatch.setattr(jobs, "SessionLocal", lambda: db, raising=True)
    monkeypatch.setattr(jobs, "execute_connector_run", _unsupported, raising=True)
    monkeypatch.setattr(jobs, "tenant_acquire", _tenant_acquire, raising=True)
    monkeypatch.setattr(jobs, "acquire_lock", _acquire, raising=True)

    result = asyncio.run(jobs.connector_run_job({"redis": object()}, str(tenant_id), str(run_id), "member-1"))

    assert result["ok"] is False
    assert result["reason"] == "unsupported_connector_id"
    assert run.status == "failed"
    assert run.error_message == "unsupported_connector_id"
    assert run.finished_at is not None
    assert db.commits == 1
