import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import BackgroundTasks, HTTPException


@dataclass
class _ConfigStub:
    id: UUID
    tenant_id: UUID
    dataset_id: UUID
    connector_id: str
    config: dict
    state: dict
    enabled: bool = True
    schedule_cron: str | None = "@hourly"
    last_run_at: datetime | None = None
    last_error: str | None = None


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


class _ClaimResult:
    def __init__(self, rowcount: int):
        self.rowcount = rowcount


class _ScheduledDB(_ConfigLookupDB):
    def __init__(self, rowcounts: list[int]):
        super().__init__(cfg=None)
        self._rowcounts = list(rowcounts)
        self.execute_calls = 0

    def execute(self, _statement):  # noqa: ANN001
        self.execute_calls += 1
        rowcount = self._rowcounts.pop(0) if self._rowcounts else 0
        return _ClaimResult(rowcount)


@pytest.mark.parametrize("mode", ["none", "exception"])
def test_shared_connector_enqueue_helper_fails_closed_when_queue_handoff_fails(monkeypatch, mode: str) -> None:  # noqa: ANN001
    import app.api.v1.connectors_runs as runs_api

    tenant_id = uuid4()
    run = SimpleNamespace(
        id=uuid4(),
        connector_id="url_batch",
        task_id="stale-task",
        status="pending",
        error_message=None,
        finished_at=None,
    )
    db = _ConfigLookupDB(cfg=None)
    background_tasks = BackgroundTasks()

    async def _enqueue_none(**_kwargs):  # noqa: ANN003, ANN202
        return None

    async def _enqueue_error(**_kwargs):  # noqa: ANN003, ANN202
        raise RuntimeError("queue down")

    monkeypatch.setattr(runs_api.connectors_module.settings, "TASK_QUEUE_ENABLED", True, raising=False)
    monkeypatch.setattr(
        runs_api.connectors_module,
        "enqueue_connector_run",
        _enqueue_none if mode == "none" else _enqueue_error,
        raising=True,
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            runs_api._enqueue_or_schedule_connector_run(  # noqa: SLF001
                db,
                background_tasks=background_tasks,
                run=run,
                tenant_id=tenant_id,
                requested_by="member-1",
            )
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == runs_api.CONNECTOR_QUEUE_UNAVAILABLE_DETAIL
    assert run.task_id is None
    assert run.status == "failed"
    assert run.error_message == "connector_queue_handoff_failed"
    assert run.finished_at is not None
    assert background_tasks.tasks == []


def test_shared_connector_enqueue_helper_rejects_unsupported_connector_before_handoff(monkeypatch) -> None:  # noqa: ANN001
    import app.api.v1.connectors_runs as runs_api

    tenant_id = uuid4()
    run = SimpleNamespace(
        id=uuid4(),
        connector_id="unknown",
        task_id=None,
        status="pending",
        error_message=None,
        finished_at=None,
    )
    db = _ConfigLookupDB(cfg=None)
    enqueue_called = False

    async def _unexpected_enqueue(**_kwargs):  # noqa: ANN003, ANN202
        nonlocal enqueue_called
        enqueue_called = True
        return "task-id"

    monkeypatch.setattr(runs_api.connectors_module.settings, "TASK_QUEUE_ENABLED", True, raising=False)
    monkeypatch.setattr(runs_api.connectors_module, "enqueue_connector_run", _unexpected_enqueue, raising=True)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            runs_api._enqueue_or_schedule_connector_run(  # noqa: SLF001
                db,
                background_tasks=BackgroundTasks(),
                run=run,
                tenant_id=tenant_id,
                requested_by="member-1",
            )
        )

    assert exc_info.value.status_code == 400
    assert enqueue_called is False
    assert run.status == "failed"
    assert run.error_message == "unsupported_connector_id"


def test_run_connector_config_uses_shared_enqueue_helper(monkeypatch) -> None:  # noqa: ANN001
    import app.api.v1.connectors_configs as configs_api

    tenant_id = uuid4()
    dataset_id = uuid4()
    cfg = _ConfigStub(
        id=uuid4(),
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        connector_id="url_batch",
        config={"urls": ["https://example.com"]},
        state={},
        schedule_cron=None,
    )
    db = _ConfigLookupDB(cfg)
    queued: list[dict[str, object]] = []

    monkeypatch.setattr(
        configs_api.connectors_module.DatasetService,
        "ensure_member",
        lambda *_args, **_kwargs: None,
        raising=True,
    )
    monkeypatch.setattr(
        configs_api.connectors_module.DatasetService,
        "get_dataset",
        lambda *_args, **_kwargs: SimpleNamespace(id=dataset_id),
        raising=True,
    )
    monkeypatch.setattr(
        configs_api.connectors_module.DatasetService,
        "assert_dataset_writable",
        lambda *_args, **_kwargs: None,
        raising=True,
    )
    monkeypatch.setattr(configs_api.connectors_module.settings, "URL_INGEST_ENABLED", True, raising=False)
    monkeypatch.setattr(configs_api, "validate_db_connector_config", lambda *_args, **_kwargs: None, raising=True)
    async def _fake_enqueue(db, *, background_tasks, run, tenant_id, requested_by):  # noqa: ANN001, ANN202
        queued.append(
            {
                "db": db,
                "background_tasks": background_tasks,
                "run": run,
                "tenant_id": tenant_id,
                "requested_by": requested_by,
            }
        )
        return {"id": run.id, "task_id": getattr(run, "task_id", None)}

    monkeypatch.setattr(
        configs_api,
        "_enqueue_or_schedule_connector_run",
        _fake_enqueue,
        raising=True,
    )

    background_tasks = BackgroundTasks()
    result = asyncio.run(
        configs_api.run_connector_config(
            config_id=cfg.id,
            background_tasks=background_tasks,
            tenant_id=tenant_id,
            account_id="member-1",
            db=db,
        )
    )

    assert result["id"] == db.added[0].id
    assert len(queued) == 1
    assert queued[0]["db"] is db
    assert queued[0]["background_tasks"] is background_tasks
    assert queued[0]["tenant_id"] == tenant_id
    assert queued[0]["requested_by"] == "member-1"
    assert queued[0]["run"].stats == {"config_id": str(cfg.id)}
    assert background_tasks.tasks == []


def test_scheduled_config_claim_dedupes_same_window_and_uses_shared_enqueue_helper(monkeypatch) -> None:  # noqa: ANN001
    import app.api.v1.connectors_schedules as schedules_api

    tenant_id = uuid4()
    dataset_id = uuid4()
    config_id = uuid4()
    now = datetime(2026, 7, 25, 10, 0, tzinfo=UTC)
    cfg_a = _ConfigStub(
        id=config_id,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        connector_id="url_batch",
        config={"urls": ["https://example.com/a"]},
        state={},
    )
    cfg_b = _ConfigStub(
        id=config_id,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        connector_id="url_batch",
        config={"urls": ["https://example.com/a"]},
        state={},
    )
    db = _ScheduledDB([1, 0])
    queued: list[UUID] = []

    async def _fake_enqueue(db, *, background_tasks, run, tenant_id, requested_by):  # noqa: ANN001, ANN202
        queued.append(run.id)
        return {"id": run.id}

    monkeypatch.setattr(schedules_api, "_enqueue_or_schedule_connector_run", _fake_enqueue, raising=True)
    monkeypatch.setattr(schedules_api, "_config_dataset_is_writable", lambda *_args, **_kwargs: True, raising=True)
    monkeypatch.setattr(schedules_api, "_disabled_connector_error", lambda *_args, **_kwargs: None, raising=True)

    ctx = schedules_api._ScheduledTickContext(  # noqa: SLF001
        background_tasks=BackgroundTasks(),
        db=db,
        tenant_id=tenant_id,
        account_id="member-1",
        now=now,
    )

    first = asyncio.run(schedules_api._process_scheduled_config(ctx, cfg_a))  # noqa: SLF001
    second = asyncio.run(schedules_api._process_scheduled_config(ctx, cfg_b))  # noqa: SLF001

    assert first == "enqueued"
    assert second == "skipped"
    assert len(queued) == 1
    assert db.execute_calls == 2
    assert len(db.added) == 1
    assert cfg_a.last_run_at == now


def test_run_connector_config_fails_closed_when_queue_handoff_fails(monkeypatch) -> None:  # noqa: ANN001
    import app.api.v1.connectors_configs as configs_api
    import app.api.v1.connectors_runs as runs_api

    tenant_id = uuid4()
    dataset_id = uuid4()
    cfg = _ConfigStub(
        id=uuid4(),
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        connector_id="url_batch",
        config={"urls": ["https://example.com"]},
        state={},
        schedule_cron=None,
        last_run_at=datetime(2026, 7, 25, 8, 0, tzinfo=UTC),
        last_error="previous_error",
    )
    db = _ConfigLookupDB(cfg)

    async def _enqueue_none(**_kwargs):  # noqa: ANN003, ANN202
        return None

    monkeypatch.setattr(
        configs_api.connectors_module.DatasetService,
        "ensure_member",
        lambda *_args, **_kwargs: None,
        raising=True,
    )
    monkeypatch.setattr(
        configs_api.connectors_module.DatasetService,
        "get_dataset",
        lambda *_args, **_kwargs: SimpleNamespace(id=dataset_id),
        raising=True,
    )
    monkeypatch.setattr(
        configs_api.connectors_module.DatasetService,
        "assert_dataset_writable",
        lambda *_args, **_kwargs: None,
        raising=True,
    )
    monkeypatch.setattr(configs_api.connectors_module.settings, "URL_INGEST_ENABLED", True, raising=False)
    monkeypatch.setattr(runs_api.connectors_module.settings, "TASK_QUEUE_ENABLED", True, raising=False)
    monkeypatch.setattr(runs_api.connectors_module, "enqueue_connector_run", _enqueue_none, raising=True)

    background_tasks = BackgroundTasks()
    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            configs_api.run_connector_config(
                config_id=cfg.id,
                background_tasks=background_tasks,
                tenant_id=tenant_id,
                account_id="member-1",
                db=db,
            )
        )

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == runs_api.CONNECTOR_QUEUE_UNAVAILABLE_DETAIL
    assert db.added[0].status == "failed"
    assert db.added[0].task_id is None
    assert cfg.last_run_at == datetime(2026, 7, 25, 8, 0, tzinfo=UTC)
    assert cfg.last_error == "connector_queue_handoff_failed"
    assert background_tasks.tasks == []


def test_scheduled_config_fails_closed_when_queue_handoff_fails(monkeypatch) -> None:  # noqa: ANN001
    import app.api.v1.connectors_runs as runs_api
    import app.api.v1.connectors_schedules as schedules_api

    tenant_id = uuid4()
    dataset_id = uuid4()
    now = datetime(2026, 7, 25, 10, 0, tzinfo=UTC)
    cfg = _ConfigStub(
        id=uuid4(),
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        connector_id="url_batch",
        config={"urls": ["https://example.com/a"]},
        state={},
    )
    db = _ScheduledDB([1, 1])

    async def _enqueue_none(**_kwargs):  # noqa: ANN003, ANN202
        return None

    monkeypatch.setattr(schedules_api, "_config_dataset_is_writable", lambda *_args, **_kwargs: True, raising=True)
    monkeypatch.setattr(schedules_api, "_disabled_connector_error", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(runs_api.connectors_module.settings, "TASK_QUEUE_ENABLED", True, raising=False)
    monkeypatch.setattr(runs_api.connectors_module, "enqueue_connector_run", _enqueue_none, raising=True)

    background_tasks = BackgroundTasks()
    ctx = schedules_api._ScheduledTickContext(  # noqa: SLF001
        background_tasks=background_tasks,
        db=db,
        tenant_id=tenant_id,
        account_id="member-1",
        now=now,
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(schedules_api._process_scheduled_config(ctx, cfg))  # noqa: SLF001

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == runs_api.CONNECTOR_QUEUE_UNAVAILABLE_DETAIL
    assert len(db.added) == 1
    assert db.added[0].status == "failed"
    assert db.added[0].task_id is None
    assert cfg.last_run_at is None
    assert cfg.last_error == "connector_queue_handoff_failed"
    assert db.execute_calls == 2
    assert background_tasks.tasks == []


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
