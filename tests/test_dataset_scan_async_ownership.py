import asyncio
import threading
from contextvars import ContextVar
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.services.runtime import retrieval_limiter
from app.tasks.queue import TaskEnqueueRejectedError
from tests.test_dataset_scan_queue_contracts import _FakeScanDB


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["profile", "precheck"])
async def test_scan_creation_owns_database_thread_and_keeps_queue_on_request_loop(monkeypatch, kind):
    from app.api.v1.datasets import precheck as dataset_precheck
    from app.api.v1.datasets import routes as datasets

    module = datasets if kind == "profile" else dataset_precheck
    model = module.DBDatasetProfileScanRun if kind == "profile" else module.DBDatasetPrecheckScanRun
    tenant_id, dataset_id = uuid4(), uuid4()
    request_loop = asyncio.get_running_loop()
    request_thread = threading.get_ident()
    sessions = []
    old_time = datetime.now(timezone.utc) - timedelta(hours=8)
    old_row = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        status="pending",
        created_at=old_time,
        updated_at=old_time,
        finished_at=None,
        error_message=None,
    )

    class Database(_FakeScanDB):
        def __init__(self):
            assert threading.get_ident() != request_thread
            super().__init__(rows_by_model={model: [old_row]})
            self.thread = threading.get_ident()
            self.closed = False
            sessions.append(self)

        def query(self, model):
            assert threading.get_ident() == self.thread
            return super().query(model)

        def commit(self):
            assert threading.get_ident() == self.thread
            super().commit()

        def close(self):
            assert threading.get_ident() == self.thread
            self.closed = True

    def permission(db, *args, **kwargs):
        assert db in sessions and threading.get_ident() == db.thread
        return object()

    async def status(job_id):
        assert asyncio.get_running_loop() is request_loop
        return None

    async def enqueue(**kwargs):
        assert asyncio.get_running_loop() is request_loop
        assert old_row.status == "failed"
        return "queued"

    monkeypatch.setattr(module, "SessionLocal", Database)
    monkeypatch.setattr(retrieval_limiter, "SessionLocal", Database)
    monkeypatch.setattr(module.settings, "TASK_QUEUE_ENABLED", True)
    monkeypatch.setattr(module, "get_task_job_status", status)
    if kind == "profile":
        monkeypatch.setattr(module.dataset_service, "get_dataset", permission)
        monkeypatch.setattr(module.dataset_service, "assert_dataset_writable", permission)
        monkeypatch.setattr(module, "enqueue_dataset_profile_scan", enqueue)
        create, body = module.create_dataset_profile_scan_run, module.DatasetProfileScanRunCreateRequest()
    else:
        monkeypatch.setattr(module, "get_dataset_for_precheck", permission)
        monkeypatch.setattr(module, "enqueue_dataset_precheck_scan", enqueue)
        create, body = (
            module.create_dataset_precheck_scan_run,
            module.DatasetPrecheckScanRunCreateRequest(root_path="/source"),
        )
    result = await create(dataset_id, body, tenant_id=tenant_id, account_id="owner")
    assert result.status == "pending"
    assert len(sessions) == 2 and all(session.closed for session in sessions)


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["profile", "precheck"])
async def test_cancelled_scan_queue_check_does_not_commit_or_leave_worker_alive(monkeypatch, kind):
    from app.api.v1.datasets import precheck as dataset_precheck
    from app.api.v1.datasets import routes as datasets

    module = datasets if kind == "profile" else dataset_precheck
    model = module.DBDatasetProfileScanRun if kind == "profile" else module.DBDatasetPrecheckScanRun
    tenant_id, dataset_id = uuid4(), uuid4()
    old_time = datetime.now(timezone.utc) - timedelta(hours=8)
    old_row = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        status="pending",
        created_at=old_time,
        updated_at=old_time,
        finished_at=None,
        error_message=None,
    )
    sessions = []
    started = asyncio.Event()

    class Database(_FakeScanDB):
        def __init__(self):
            super().__init__(rows_by_model={model: [old_row]})
            self.closed = False
            sessions.append(self)

        def close(self):
            self.closed = True

    async def status(job_id):
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(module, "SessionLocal", Database)
    monkeypatch.setattr(module.settings, "TASK_QUEUE_ENABLED", True)
    monkeypatch.setattr(module, "get_task_job_status", status)
    if kind == "profile":
        monkeypatch.setattr(module.dataset_service, "get_dataset", lambda *a, **k: object())
        monkeypatch.setattr(module.dataset_service, "assert_dataset_writable", lambda *a, **k: None)
        create, body = module.create_dataset_profile_scan_run, module.DatasetProfileScanRunCreateRequest()
    else:
        monkeypatch.setattr(module, "get_dataset_for_precheck", lambda *a, **k: object())
        create, body = (
            module.create_dataset_precheck_scan_run,
            module.DatasetPrecheckScanRunCreateRequest(root_path="/source"),
        )
    task = asyncio.create_task(create(dataset_id, body, tenant_id=tenant_id, account_id="owner"))
    await asyncio.wait_for(started.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert sessions and all(session.closed and session.commit_calls == 0 for session in sessions)
    assert old_row.status == "pending"


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["profile", "precheck"])
async def test_expiry_does_not_overwrite_heartbeat_during_queue_check(monkeypatch, kind):
    from app.api.v1.datasets import precheck as dataset_precheck
    from app.api.v1.datasets import routes as datasets
    from app.services.datasets.scan_session import CurrentThreadScanSession

    module = datasets if kind == "profile" else dataset_precheck
    model = module.DBDatasetProfileScanRun if kind == "profile" else module.DBDatasetPrecheckScanRun
    tenant_id, dataset_id = uuid4(), uuid4()
    old_time = datetime.now(timezone.utc) - timedelta(hours=8)
    row = SimpleNamespace(id=uuid4(), status="running", created_at=old_time, updated_at=old_time, finished_at=None)
    db = _FakeScanDB(rows_by_model={model: [row]})
    heartbeat = datetime.now(timezone.utc)

    async def status(job_id):
        row.updated_at = heartbeat
        return None

    monkeypatch.setattr(module.settings, "TASK_QUEUE_ENABLED", True)
    monkeypatch.setattr(module, "get_task_job_status", status)
    expire = (
        module._expire_stale_dataset_profile_scan_runs if kind == "profile" else module._expire_stale_precheck_scan_runs
    )
    assert await expire(CurrentThreadScanSession(db), tenant_id=tenant_id, dataset_id=dataset_id) == 0
    assert row.status == "running" and row.updated_at == heartbeat
    assert db.flush_calls == db.commit_calls == 0


@pytest.mark.asyncio
async def test_cancellation_while_database_query_runs_prevents_later_commit():
    from app.services.datasets.scan_session import DatasetScanSession

    started, release = threading.Event(), threading.Event()
    request_thread = threading.get_ident()
    calls = []

    class Database:
        def __init__(self):
            self.thread = threading.get_ident()
            assert self.thread != request_thread

        def commit(self):
            calls.append("commit")

        def close(self):
            assert threading.get_ident() == self.thread
            calls.append("closed")

    async with DatasetScanSession(Database) as transaction:

        def query_then_write(db):
            started.set()
            assert release.wait(5)
            transaction.raise_if_cancelled()
            db.commit()

        task = asyncio.create_task(transaction.run(query_then_write))
        assert await asyncio.to_thread(started.wait, 5)
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert calls == ["closed"]


@pytest.mark.asyncio
async def test_scan_session_close_failure_preserves_original_transaction_error():
    from app.services.datasets.scan_session import DatasetScanSession

    class Database:
        def close(self):
            raise RuntimeError("close failed")

    def fail(db):
        raise ValueError("transaction failed")

    with pytest.raises(ValueError, match="transaction failed"):
        async with DatasetScanSession(Database) as transaction:
            await transaction.run(fail)


@pytest.mark.asyncio
async def test_scan_worker_receives_request_context_without_changing_the_request():
    from app.services.datasets.scan_session import DatasetScanSession

    request_id = ContextVar("scan_test_request_id", default="missing")
    token = request_id.set("request-1")

    class Database:
        def close(self):
            pass

    def inspect_context(db):
        value = request_id.get()
        request_id.set("worker-only")
        return value

    try:
        async with DatasetScanSession(Database) as transaction:
            assert await transaction.run(inspect_context) == "request-1"
        assert request_id.get() == "request-1"
    finally:
        request_id.reset(token)


@pytest.mark.asyncio
async def test_repeated_cancellation_waits_for_scan_session_close():
    from app.services.datasets.scan_session import DatasetScanSession

    closing, release, closed = threading.Event(), threading.Event(), threading.Event()

    class Database:
        def close(self):
            closing.set()
            assert release.wait(5)
            closed.set()

    async def use_session():
        async with DatasetScanSession(Database) as transaction:
            await transaction.run(lambda db: None)

    task = asyncio.create_task(use_session())
    assert await asyncio.to_thread(closing.wait, 5)
    try:
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert closed.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize("transaction_fails", [False, True])
async def test_close_deadline_settles_native_close_and_preserves_transaction_error(monkeypatch, transaction_fails):
    from app.services.datasets import scan_session as dataset_scan_session

    original_deadline = dataset_scan_session.anyio.fail_after
    monkeypatch.setattr(
        dataset_scan_session.anyio, "fail_after", lambda _delay, *, shield: original_deadline(0.02, shield=shield)
    )
    closing, release, closed = threading.Event(), threading.Event(), threading.Event()

    class Database:
        def close(self):
            closing.set()
            assert release.wait(5)
            closed.set()

    async def release_after_deadline():
        assert await asyncio.to_thread(closing.wait, 5)
        await asyncio.sleep(0.05)
        release.set()

    async def use_session():
        async with dataset_scan_session.DatasetScanSession(Database) as transaction:
            await transaction.run(lambda db: None)
            if transaction_fails:
                raise ValueError("transaction failed")

    releasing = asyncio.create_task(release_after_deadline())
    try:
        expected = ValueError if transaction_fails else TimeoutError
        with pytest.raises(expected):
            await use_session()
    finally:
        release.set()
        await releasing
    assert closed.is_set()


@pytest.mark.asyncio
@pytest.mark.parametrize("kind", ["profile", "precheck"])
@pytest.mark.parametrize("rollback_fails", [False, True])
async def test_compensation_query_failure_preserves_enqueue_error(monkeypatch, kind, rollback_fails):
    from app.api.v1.datasets import precheck as dataset_precheck
    from app.api.v1.datasets import routes as datasets

    module = datasets if kind == "profile" else dataset_precheck
    tenant_id, dataset_id = uuid4(), uuid4()
    broken = threading.Event()

    class Database(_FakeScanDB):
        def query(self, model):
            if broken.is_set():
                raise RuntimeError("database unavailable during compensation")
            return super().query(model)

        def rollback(self):
            if rollback_fails and broken.is_set():
                raise RuntimeError("rollback connection lost")
            super().rollback()

    async def enqueue(**kwargs):
        broken.set()
        raise TaskEnqueueRejectedError("queue rejected")

    monkeypatch.setattr(module, "SessionLocal", Database)
    monkeypatch.setattr(retrieval_limiter, "SessionLocal", Database)
    if kind == "profile":
        monkeypatch.setattr(module.dataset_service, "get_dataset", lambda *a, **k: object())
        monkeypatch.setattr(module.dataset_service, "assert_dataset_writable", lambda *a, **k: None)
        monkeypatch.setattr(module, "enqueue_dataset_profile_scan", enqueue)
        create, body = module.create_dataset_profile_scan_run, module.DatasetProfileScanRunCreateRequest()
    else:
        monkeypatch.setattr(module, "get_dataset_for_precheck", lambda *a, **k: object())
        monkeypatch.setattr(module, "enqueue_dataset_precheck_scan", enqueue)
        create, body = (
            module.create_dataset_precheck_scan_run,
            module.DatasetPrecheckScanRunCreateRequest(root_path="/source"),
        )
    with pytest.raises(HTTPException) as error:
        await create(dataset_id, body, tenant_id=tenant_id, account_id="owner")
    assert error.value.status_code == 503
    assert isinstance(error.value.__cause__, TaskEnqueueRejectedError)
