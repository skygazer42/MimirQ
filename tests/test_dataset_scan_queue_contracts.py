import sys
import uuid
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from importlib import import_module, util
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from fastapi import BackgroundTasks, HTTPException
from sqlalchemy.exc import IntegrityError


def test_scan_uniqueness_migration_retries_concurrent_indexes_safely(monkeypatch) -> None:
    fake_alembic = ModuleType("alembic")
    fake_alembic.op = SimpleNamespace()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "alembic", fake_alembic)
    migration_path = Path(__file__).parents[1] / "alembic" / "versions" / "0025_scan_run_active_uniqueness.py"
    spec = util.spec_from_file_location("mimirq_scan_uniqueness_migration", migration_path)
    assert spec is not None and spec.loader is not None
    migration = util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    operations: list[tuple[str, str, dict[str, object]]] = []

    monkeypatch.setattr(
        migration.op,
        "get_bind",
        lambda: SimpleNamespace(dialect=SimpleNamespace(name="postgresql")),
        raising=False,
    )
    monkeypatch.setattr(
        migration.op,
        "get_context",
        lambda: SimpleNamespace(autocommit_block=lambda: nullcontext()),
        raising=False,
    )
    monkeypatch.setattr(migration.op, "execute", lambda _statement: None, raising=False)
    monkeypatch.setattr(
        migration.op,
        "drop_index",
        lambda name, **kwargs: operations.append(("drop", name, kwargs)),
        raising=False,
    )
    monkeypatch.setattr(
        migration.op,
        "create_index",
        lambda name, _table, _columns, **kwargs: operations.append(("create", name, kwargs)),
        raising=False,
    )

    migration.upgrade()

    assert [operation for operation, _name, _kwargs in operations] == [
        "drop",
        "drop",
        "create",
        "create",
    ]
    assert all(kwargs.get("if_exists") is True for operation, _name, kwargs in operations if operation == "drop")
    assert all(kwargs.get("postgresql_concurrently") is True for _operation, _name, kwargs in operations)


class _ScanRunQuery:
    def __init__(self, rows: list[object]) -> None:
        self._rows = rows

    def filter(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN201
        return self

    def order_by(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN201
        return self

    def all(self) -> list[object]:
        return list(self._rows)

    def first(self):  # noqa: ANN201
        active = [row for row in self._rows if str(getattr(row, "status", "") or "") in {"pending", "running"}]
        active.sort(
            key=lambda row: getattr(row, "created_at", None) or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        return active[0] if active else None

    def count(self) -> int:
        return len([row for row in self._rows if str(getattr(row, "status", "") or "") in {"pending", "running"}])


class _FakeScanDB:
    def __init__(
        self,
        *,
        rows_by_model: dict[type[object], list[object]] | None = None,
        on_insert_conflict=None,  # noqa: ANN001
    ) -> None:
        self.rows_by_model = {model: list(rows) for model, rows in (rows_by_model or {}).items()}
        self.pending_added: list[object] = []
        self.commit_calls = 0
        self.rollback_calls = 0
        self.flush_calls = 0
        self._on_insert_conflict = on_insert_conflict

    def query(self, model):  # noqa: ANN001, ANN201
        return _ScanRunQuery(self.rows_by_model.setdefault(model, []))

    def add(self, obj) -> None:  # noqa: ANN001
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        if getattr(obj, "created_at", None) is None:
            obj.created_at = now
        if getattr(obj, "updated_at", None) is None:
            obj.updated_at = now
        self.pending_added.append(obj)

    def commit(self) -> None:
        self.commit_calls += 1
        if self.pending_added and self._on_insert_conflict is not None:
            self._on_insert_conflict(self)
            raise IntegrityError("scan run insert conflict", None, None)
        for obj in self.pending_added:
            self.rows_by_model.setdefault(type(obj), []).append(obj)
        self.pending_added.clear()

    def refresh(self, obj) -> None:  # noqa: ANN001
        if getattr(obj, "updated_at", None) is None:
            obj.updated_at = datetime.now(timezone.utc)

    def rollback(self) -> None:
        self.rollback_calls += 1
        self.pending_added.clear()

    def flush(self) -> None:
        self.flush_calls += 1


class _DatasetDeleteDB:
    def __init__(self, *, doc_count: int = 0) -> None:
        self.doc_count = doc_count
        self.deleted: list[object] = []
        self.commit_calls = 0

    def query(self, model):  # noqa: ANN001, ANN201
        class _Query:
            def __init__(self, count_value: int) -> None:
                self._count_value = count_value

            def filter(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN201
                return self

            def count(self) -> int:
                return self._count_value

        return _Query(self.doc_count if getattr(model, "__name__", "") == "Document" else 0)

    def delete(self, obj) -> None:  # noqa: ANN001
        self.deleted.append(obj)

    def commit(self) -> None:
        self.commit_calls += 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("enqueue_name", "job_name"),
    [
        ("enqueue_dataset_profile_scan", "dataset_profile_scan_job"),
        ("enqueue_dataset_precheck_scan", "dataset_precheck_scan_job"),
    ],
)
async def test_scan_enqueue_raises_when_arq_rejects_job(
    monkeypatch: pytest.MonkeyPatch,
    enqueue_name: str,
    job_name: str,
) -> None:
    from app.tasks import queue

    class _Queue:
        async def enqueue_job(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN202
            assert args[0] == job_name
            assert kwargs["_job_id"].startswith("scan:")
            return None

    async def _get_queue():  # noqa: ANN202
        return _Queue()

    async def _job_status(_job_id: str):  # noqa: ANN202
        return None

    monkeypatch.setattr(queue, "get_queue", _get_queue, raising=True)
    monkeypatch.setattr(queue, "get_task_job_status", _job_status, raising=True)

    enqueue = getattr(queue, enqueue_name)
    with pytest.raises(queue.TaskEnqueueRejectedError):
        await enqueue(
            tenant_id=uuid.uuid4(),
            dataset_id=uuid.uuid4(),
            scan_run_id=uuid.uuid4(),
            requested_by="member-1",
            job_id="scan:1",
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("enqueue_name", "job_name"),
    [
        ("enqueue_dataset_profile_scan", "dataset_profile_scan_job"),
        ("enqueue_dataset_precheck_scan", "dataset_precheck_scan_job"),
    ],
)
async def test_scan_enqueue_treats_live_duplicate_job_as_success(
    monkeypatch: pytest.MonkeyPatch,
    enqueue_name: str,
    job_name: str,
) -> None:
    from app.tasks import queue

    class _Queue:
        async def enqueue_job(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN202
            assert args[0] == job_name
            assert kwargs["_job_id"] == "scan:dup"
            return None

    async def _get_queue():  # noqa: ANN202
        return _Queue()

    async def _job_status(_job_id: str):  # noqa: ANN202
        return "queued"

    monkeypatch.setattr(queue, "get_queue", _get_queue, raising=True)
    monkeypatch.setattr(queue, "get_task_job_status", _job_status, raising=True)

    enqueue = getattr(queue, enqueue_name)
    result = await enqueue(
        tenant_id=uuid.uuid4(),
        dataset_id=uuid.uuid4(),
        scan_run_id=uuid.uuid4(),
        requested_by="member-1",
        job_id="scan:dup",
    )

    assert result == "scan:dup"


@pytest.mark.asyncio
async def test_create_dataset_profile_scan_run_marks_failed_when_enqueue_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.datasets as datasets_api

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    db = _FakeScanDB(rows_by_model={datasets_api.DBDatasetProfileScanRun: []})
    background_tasks = BackgroundTasks()

    monkeypatch.setattr(
        datasets_api.DatasetService,
        "get_dataset",
        lambda *_args, **_kwargs: SimpleNamespace(id=dataset_id, tenant_id=tenant_id),
        raising=True,
    )
    monkeypatch.setattr(
        datasets_api.DatasetService,
        "assert_dataset_writable",
        lambda *_args, **_kwargs: None,
        raising=True,
    )
    monkeypatch.setattr(
        datasets_api,
        "_scan_run_out_from_row",
        lambda row: {"id": row.id, "tenant_id": row.tenant_id, "dataset_id": row.dataset_id, "status": row.status},
        raising=True,
    )

    async def _reject_enqueue(**_kwargs):  # noqa: ANN202
        raise datasets_api.TaskEnqueueRejectedError("arq did not accept dataset profile scan job")

    monkeypatch.setattr(datasets_api, "enqueue_dataset_profile_scan", _reject_enqueue, raising=True)

    with pytest.raises(HTTPException) as exc_info:
        await datasets_api.create_dataset_profile_scan_run(
            dataset_id=dataset_id,
            body=datasets_api.DatasetProfileScanRunCreateRequest(),
            background_tasks=background_tasks,
            tenant_id=tenant_id,
            account_id="member-1",
            db=db,
        )

    assert exc_info.value.status_code == 503
    rows = db.rows_by_model[datasets_api.DBDatasetProfileScanRun]
    assert len(rows) == 1
    assert rows[0].status == "failed"
    assert "enqueue" in str(rows[0].error_message or "")
    assert rows[0].finished_at is not None
    assert background_tasks.tasks == []


@pytest.mark.asyncio
async def test_create_dataset_profile_scan_run_replaces_stale_pending_and_falls_back_to_background(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.datasets as datasets_api

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    stale_time = datetime.now(timezone.utc) - timedelta(hours=1)
    stale_row = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        status="pending",
        created_at=stale_time,
        updated_at=stale_time,
        finished_at=None,
        error_message=None,
    )
    db = _FakeScanDB(rows_by_model={datasets_api.DBDatasetProfileScanRun: [stale_row]})
    background_tasks = BackgroundTasks()

    monkeypatch.setattr(
        datasets_api.DatasetService,
        "get_dataset",
        lambda *_args, **_kwargs: SimpleNamespace(id=dataset_id, tenant_id=tenant_id),
        raising=True,
    )
    monkeypatch.setattr(
        datasets_api.DatasetService,
        "assert_dataset_writable",
        lambda *_args, **_kwargs: None,
        raising=True,
    )
    monkeypatch.setattr(
        datasets_api,
        "_scan_run_out_from_row",
        lambda row: {"id": row.id, "tenant_id": row.tenant_id, "dataset_id": row.dataset_id, "status": row.status},
        raising=True,
    )

    async def _queue_disabled(**_kwargs):  # noqa: ANN202
        return None

    monkeypatch.setattr(datasets_api, "enqueue_dataset_profile_scan", _queue_disabled, raising=True)

    result = await datasets_api.create_dataset_profile_scan_run(
        dataset_id=dataset_id,
        body=datasets_api.DatasetProfileScanRunCreateRequest(),
        background_tasks=background_tasks,
        tenant_id=tenant_id,
        account_id="member-1",
        db=db,
    )

    assert result["status"] == "pending"
    assert stale_row.status == "failed"
    assert stale_row.finished_at is not None
    assert "stale" in str(stale_row.error_message or "")
    assert len(db.rows_by_model[datasets_api.DBDatasetProfileScanRun]) == 2
    assert len(background_tasks.tasks) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("module_name", "model_name", "helper_name"),
    [
        ("app.api.v1.datasets", "DBDatasetProfileScanRun", "_expire_stale_dataset_profile_scan_runs"),
        ("app.api.v1.dataset_precheck", "DBDatasetPrecheckScanRun", "_expire_stale_precheck_scan_runs"),
    ],
)
async def test_stale_pending_scan_is_preserved_when_arq_job_is_still_live(
    monkeypatch: pytest.MonkeyPatch,
    module_name: str,
    model_name: str,
    helper_name: str,
) -> None:
    import importlib

    api_module = importlib.import_module(module_name)
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    stale_time = datetime.now(timezone.utc) - timedelta(hours=1)
    row = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        status="pending",
        created_at=stale_time,
        updated_at=stale_time,
        finished_at=None,
        error_message=None,
    )
    model = getattr(api_module, model_name)
    db = _FakeScanDB(rows_by_model={model: [row]})

    monkeypatch.setattr(api_module.settings, "TASK_QUEUE_ENABLED", True, raising=False)

    async def _job_status(_job_id: str):  # noqa: ANN202
        return "queued"

    monkeypatch.setattr(api_module, "get_task_job_status", _job_status, raising=True)

    expired = await getattr(api_module, helper_name)(db, tenant_id=tenant_id, dataset_id=dataset_id)

    assert expired == 0
    assert row.status == "pending"
    assert row.finished_at is None
    assert db.flush_calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("module_name", "model_name", "helper_name", "age", "expected_expired"),
    [
        (
            "app.api.v1.datasets",
            "DBDatasetProfileScanRun",
            "_expire_stale_dataset_profile_scan_runs",
            timedelta(hours=1),
            0,
        ),
        (
            "app.api.v1.dataset_precheck",
            "DBDatasetPrecheckScanRun",
            "_expire_stale_precheck_scan_runs",
            timedelta(hours=1),
            0,
        ),
        (
            "app.api.v1.datasets",
            "DBDatasetProfileScanRun",
            "_expire_stale_dataset_profile_scan_runs",
            timedelta(hours=3),
            1,
        ),
        (
            "app.api.v1.dataset_precheck",
            "DBDatasetPrecheckScanRun",
            "_expire_stale_precheck_scan_runs",
            timedelta(hours=3),
            1,
        ),
    ],
)
async def test_stale_pending_scan_uses_hard_expiry_when_queue_status_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    module_name: str,
    model_name: str,
    helper_name: str,
    age: timedelta,
    expected_expired: int,
) -> None:
    api_module = import_module(module_name)
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    stale_time = datetime.now(timezone.utc) - age
    row = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        status="pending",
        created_at=stale_time,
        updated_at=stale_time,
        finished_at=None,
        error_message=None,
    )
    model = getattr(api_module, model_name)
    db = _FakeScanDB(rows_by_model={model: [row]})
    monkeypatch.setattr(api_module.settings, "TASK_QUEUE_ENABLED", True, raising=False)

    async def _job_status(_job_id: str):  # noqa: ANN202
        raise RuntimeError("redis unavailable")

    monkeypatch.setattr(api_module, "get_task_job_status", _job_status, raising=True)

    expired = await getattr(api_module, helper_name)(db, tenant_id=tenant_id, dataset_id=dataset_id)

    assert expired == expected_expired
    assert row.status == ("failed" if expected_expired else "pending")
    assert db.flush_calls == expected_expired


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("module_name", "model_name", "helper_name"),
    [
        ("app.api.v1.datasets", "DBDatasetProfileScanRun", "_expire_stale_dataset_profile_scan_runs"),
        ("app.api.v1.dataset_precheck", "DBDatasetPrecheckScanRun", "_expire_stale_precheck_scan_runs"),
    ],
)
async def test_stale_running_scan_is_failed_when_job_is_not_live(
    monkeypatch: pytest.MonkeyPatch,
    module_name: str,
    model_name: str,
    helper_name: str,
) -> None:
    import importlib

    api_module = importlib.import_module(module_name)
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    stale_time = datetime.now(timezone.utc) - timedelta(hours=8)
    row = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        status="running",
        created_at=stale_time,
        updated_at=stale_time,
        finished_at=None,
        error_message=None,
    )
    model = getattr(api_module, model_name)
    db = _FakeScanDB(rows_by_model={model: [row]})

    monkeypatch.setattr(api_module.settings, "TASK_QUEUE_ENABLED", True, raising=False)

    async def _job_status(_job_id: str):  # noqa: ANN202
        return None

    monkeypatch.setattr(api_module, "get_task_job_status", _job_status, raising=True)

    expired = await getattr(api_module, helper_name)(db, tenant_id=tenant_id, dataset_id=dataset_id)

    assert expired == 1
    assert row.status == "failed"
    assert row.finished_at is not None
    assert row.error_message == "stale_running_scan_replaced"
    assert db.flush_calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("module_name", "model_name", "helper_name"),
    [
        ("app.api.v1.datasets", "DBDatasetProfileScanRun", "_expire_stale_dataset_profile_scan_runs"),
        ("app.api.v1.dataset_precheck", "DBDatasetPrecheckScanRun", "_expire_stale_precheck_scan_runs"),
    ],
)
async def test_stale_running_scan_is_preserved_when_arq_job_is_still_live(
    monkeypatch: pytest.MonkeyPatch,
    module_name: str,
    model_name: str,
    helper_name: str,
) -> None:
    import importlib

    api_module = importlib.import_module(module_name)
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    stale_time = datetime.now(timezone.utc) - timedelta(hours=8)
    row = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        status="running",
        created_at=stale_time,
        updated_at=stale_time,
        finished_at=None,
        error_message=None,
    )
    model = getattr(api_module, model_name)
    db = _FakeScanDB(rows_by_model={model: [row]})

    monkeypatch.setattr(api_module.settings, "TASK_QUEUE_ENABLED", True, raising=False)

    async def _job_status(_job_id: str):  # noqa: ANN202
        return "in_progress"

    monkeypatch.setattr(api_module, "get_task_job_status", _job_status, raising=True)

    expired = await getattr(api_module, helper_name)(db, tenant_id=tenant_id, dataset_id=dataset_id)

    assert expired == 0
    assert row.status == "running"
    assert row.finished_at is None
    assert db.flush_calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("module_name", "model_name", "helper_name", "scan_kind"),
    [
        ("app.api.v1.datasets", "DBDatasetProfileScanRun", "_expire_stale_dataset_profile_scan_runs", "profile"),
        ("app.api.v1.dataset_precheck", "DBDatasetPrecheckScanRun", "_expire_stale_precheck_scan_runs", "precheck"),
    ],
)
async def test_stale_running_scan_is_preserved_by_local_registry_when_queue_disabled(
    monkeypatch: pytest.MonkeyPatch,
    module_name: str,
    model_name: str,
    helper_name: str,
    scan_kind: str,
) -> None:
    import importlib

    from app.tasks.queue import register_local_scan_run_active, unregister_local_scan_run_active

    api_module = importlib.import_module(module_name)
    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    run_id = uuid.uuid4()
    stale_time = datetime.now(timezone.utc) - timedelta(hours=8)
    row = SimpleNamespace(
        id=run_id,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        status="running",
        created_at=stale_time,
        updated_at=stale_time,
        finished_at=None,
        error_message=None,
    )
    model = getattr(api_module, model_name)
    db = _FakeScanDB(rows_by_model={model: [row]})

    monkeypatch.setattr(api_module.settings, "TASK_QUEUE_ENABLED", False, raising=False)
    register_local_scan_run_active(
        kind=scan_kind,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        scan_run_id=run_id,
    )
    try:
        expired = await getattr(api_module, helper_name)(db, tenant_id=tenant_id, dataset_id=dataset_id)
    finally:
        unregister_local_scan_run_active(
            kind=scan_kind,
            tenant_id=tenant_id,
            dataset_id=dataset_id,
            scan_run_id=run_id,
        )

    assert expired == 0
    assert row.status == "running"
    assert row.finished_at is None
    assert db.flush_calls == 0


@pytest.mark.asyncio
async def test_create_dataset_precheck_scan_run_returns_409_on_concurrent_insert_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.dataset_precheck as precheck_api

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    conflict_row = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        status="pending",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
        finished_at=None,
        error_message=None,
    )

    def _inject_conflict(db: _FakeScanDB) -> None:
        db.rows_by_model.setdefault(precheck_api.DBDatasetPrecheckScanRun, []).append(conflict_row)

    db = _FakeScanDB(
        rows_by_model={precheck_api.DBDatasetPrecheckScanRun: []},
        on_insert_conflict=_inject_conflict,
    )
    background_tasks = BackgroundTasks()

    monkeypatch.setattr(
        precheck_api,
        "get_dataset_for_precheck",
        lambda *_args, **_kwargs: SimpleNamespace(id=dataset_id, tenant_id=tenant_id),
        raising=True,
    )
    monkeypatch.setattr(
        precheck_api,
        "_scan_run_out_from_row",
        lambda row: {"id": row.id, "tenant_id": row.tenant_id, "dataset_id": row.dataset_id, "status": row.status},
        raising=True,
    )

    with pytest.raises(HTTPException) as exc_info:
        await precheck_api.create_dataset_precheck_scan_run(
            dataset_id=dataset_id,
            body=precheck_api.DatasetPrecheckScanRunCreateRequest(root_path="/tmp/dataset"),
            background_tasks=background_tasks,
            tenant_id=tenant_id,
            account_id="member-1",
            db=db,
        )

    assert exc_info.value.status_code == 409
    assert "pending/running" in str(exc_info.value.detail)
    assert len(db.rows_by_model[precheck_api.DBDatasetPrecheckScanRun]) == 1
    assert db.rollback_calls == 1
    assert background_tasks.tasks == []


def test_delete_dataset_reconciles_stale_scans_before_active_scan_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.datasets as datasets_api

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    dataset = SimpleNamespace(id=dataset_id, tenant_id=tenant_id)
    db = _DatasetDeleteDB(doc_count=0)
    calls: list[str] = []

    monkeypatch.setattr(
        datasets_api.DatasetService,
        "get_dataset",
        lambda *_args, **_kwargs: dataset,
        raising=True,
    )
    monkeypatch.setattr(
        datasets_api.DatasetService,
        "assert_dataset_writable",
        lambda *_args, **_kwargs: None,
        raising=True,
    )

    def _reconcile(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        calls.append("reconcile")
        return (1, 1)

    def _assert_no_active(*_args, **_kwargs) -> None:  # noqa: ANN002, ANN003
        assert calls == ["reconcile"]
        calls.append("assert")

    monkeypatch.setattr(datasets_api, "_reconcile_stale_dataset_scan_runs_sync", _reconcile, raising=True)
    monkeypatch.setattr(datasets_api, "_assert_no_active_dataset_scans", _assert_no_active, raising=True)
    monkeypatch.setattr(datasets_api, "_precheck_run_ids_for_dataset", lambda *_args, **_kwargs: [], raising=True)
    monkeypatch.setattr(datasets_api, "_cleanup_dataset_table_store", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(
        datasets_api, "_cleanup_dataset_precheck_artifacts", lambda *_args, **_kwargs: None, raising=True
    )

    result = datasets_api.delete_dataset(
        dataset_id=dataset_id,
        tenant_id=tenant_id,
        account_id="member-1",
        db=db,
    )

    assert result is None
    assert calls[:2] == ["reconcile", "assert"]
    assert db.deleted == [dataset]
    assert db.commit_calls == 1


@pytest.mark.asyncio
async def test_purge_dataset_reconciles_stale_scans_before_active_scan_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.api.v1.datasets as datasets_api

    tenant_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    document_id = uuid.uuid4()
    calls: list[str] = []

    monkeypatch.setattr(datasets_api, "ensure_tenant_permission", lambda *_args, **_kwargs: None, raising=True)
    monkeypatch.setattr(
        datasets_api.DatasetService,
        "get_dataset",
        lambda *_args, **_kwargs: SimpleNamespace(id=dataset_id, tenant_id=tenant_id),
        raising=True,
    )

    async def _reconcile(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        calls.append("reconcile")
        return (1, 1)

    def _assert_no_active(*_args, **_kwargs) -> None:  # noqa: ANN002, ANN003
        assert calls == ["reconcile"]
        calls.append("assert")

    monkeypatch.setattr(datasets_api, "_reconcile_stale_dataset_scan_runs", _reconcile, raising=True)
    monkeypatch.setattr(datasets_api, "_assert_no_active_dataset_scans", _assert_no_active, raising=True)
    monkeypatch.setattr(
        datasets_api, "_dataset_document_ids_for_purge", lambda *_args, **_kwargs: [document_id], raising=True
    )
    monkeypatch.setattr(datasets_api, "_record_dataset_purge_audit", lambda *_args, **_kwargs: None, raising=True)

    result = await datasets_api.purge_dataset_documents(
        dataset_id=dataset_id,
        max_delete=100,
        dry_run=True,
        tenant_id=tenant_id,
        account_id="member-1",
        db=SimpleNamespace(),
    )

    assert calls[:2] == ["reconcile", "assert"]
    assert result.eligible == 1
    assert result.deleted == 0
