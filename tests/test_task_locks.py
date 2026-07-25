from uuid import uuid4

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app.tasks import locks


class FakeRetryError(Exception):
    def __init__(self, *, defer: int) -> None:
        super().__init__(f"retry defer={defer}")
        self.defer = defer


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, object] = {}
        self.ttl: dict[str, int] = {}
        self.eval_calls: list[tuple[tuple[str, ...], tuple[object, ...]]] = []
        self.forbid_split_lock_ops = False

    def _guard(self, key: str, op: str) -> None:
        if self.forbid_split_lock_ops and key.startswith("lock:"):
            raise AssertionError(f"lock op should be atomic via Lua, got {op}")

    async def set(self, key: str, value: object, *, ex: int | None = None, nx: bool = False) -> bool:
        self._guard(key, "set")
        if nx and key in self.store:
            return False
        self.store[key] = value
        if ex is not None:
            self.ttl[key] = int(ex)
        return True

    async def get(self, key: str) -> object | None:
        self._guard(key, "get")
        return self.store.get(key)

    async def delete(self, key: str) -> int:
        self._guard(key, "delete")
        existed = int(key in self.store)
        self.store.pop(key, None)
        self.ttl.pop(key, None)
        return existed

    async def eval(self, _script: str, numkeys: int, *values: object) -> int:
        keys = tuple(str(item) for item in values[:numkeys])
        args = tuple(values[numkeys:])
        self.eval_calls.append((keys, args))
        key = keys[0]

        if len(args) == 1:
            expected = args[0]
            if self.store.get(key) == expected:
                self.store.pop(key, None)
                self.ttl.pop(key, None)
                return 1
            return 0
        raise AssertionError(f"unexpected Lua arguments: {args!r}")

    async def execute_command(self, command: str, script: str, numkeys: int, *values: object) -> int:
        assert command == "EVAL"
        return await self.eval(script, numkeys, *values)


class FailingRedis(FakeRedis):
    async def set(self, key: str, value: object, *, ex: int | None = None, nx: bool = False) -> bool:
        raise RuntimeError("redis unavailable")


class _QueryStub:
    def __init__(self, value) -> None:  # noqa: ANN001
        self._value = value

    def filter(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        return self

    def first(self):  # noqa: ANN201
        return self._value


class _RunDB:
    def __init__(self, run) -> None:  # noqa: ANN001
        self.run = run
        self.commits = 0
        self.rollbacks = 0

    def query(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN201
        return _QueryStub(self.run)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        return None


class _ValueDB(_RunDB):
    pass


class _FailingCommitDB(_RunDB):
    def commit(self) -> None:
        raise SQLAlchemyError("commit failed")


class _KGQueryStub:
    def __init__(self, db, model) -> None:  # noqa: ANN001
        self._db = db
        self._model = model

    def filter(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        return self

    def order_by(self, *_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        return self

    def first(self):  # noqa: ANN201
        name = getattr(self._model, "__name__", "")
        if name == "Document":
            return self._db.document
        if name == "Dataset":
            return self._db.dataset
        return None

    def all(self):  # noqa: ANN201
        if getattr(self._model, "__name__", "") == "DocumentChunk":
            return list(self._db.chunks)
        return []


class _KGDB:
    def __init__(self, *, document, chunks, dataset=None) -> None:  # noqa: ANN001
        self.document = document
        self.chunks = list(chunks)
        self.dataset = dataset
        self.commits = 0
        self.rollbacks = 0

    def query(self, model):  # noqa: ANN001, ANN201
        return _KGQueryStub(self, model)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        return None


def test_lock_values_are_unique_for_same_requester() -> None:
    values = {locks.make_lock_value("account-a") for _ in range(32)}

    assert len(values) == 32


def test_task_job_lock_ttl_tracks_timeout_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.tasks import jobs

    monkeypatch.setattr(jobs.settings, "TASK_JOB_TIMEOUT_SEC", 123, raising=False)

    assert jobs._task_job_lock_ttl_sec() == 40 * 60
    assert jobs._task_job_lock_ttl_sec(minimum_sec=60 * 60) == 60 * 60


def test_task_semaphore_ttl_keeps_hour_floor(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.tasks import jobs

    monkeypatch.setattr(jobs.settings, "TASK_JOB_TIMEOUT_SEC", 123, raising=False)

    assert jobs._TASK_SEMAPHORE_TTL_SEC == 60 * 60


@pytest.mark.asyncio
async def test_release_lock_keeps_replaced_lock() -> None:
    redis = FakeRedis()
    redis.store["lock:doc:1"] = "owner-b"
    redis.forbid_split_lock_ops = True

    await locks.release_lock(redis, key="lock:doc:1", value="owner-a")

    assert redis.store["lock:doc:1"] == "owner-b"
    assert redis.eval_calls == [(("lock:doc:1",), ("owner-a",))]


@pytest.mark.asyncio
async def test_acquire_lock_defaults_fail_open_on_redis_error() -> None:
    assert await locks.acquire_lock(FailingRedis(), key="lock:doc:1", value="owner-a", ttl_sec=60) is True


@pytest.mark.asyncio
async def test_acquire_lock_can_fail_closed_on_redis_error() -> None:
    with pytest.raises(RuntimeError, match="redis unavailable"):
        await locks.acquire_lock(FailingRedis(), key="lock:doc:1", value="owner-a", ttl_sec=60, fail_open=False)


@pytest.mark.asyncio
async def test_acquire_lock_can_fail_closed_without_redis_client() -> None:
    with pytest.raises(RuntimeError, match="Redis client unavailable"):
        await locks.acquire_lock(None, key="lock:doc:1", value="owner-a", ttl_sec=60, fail_open=False)


@pytest.mark.asyncio
async def test_acquire_lock_retries_on_redis_error_when_retry_requested(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(locks, "get_retry_exc", lambda: FakeRetryError)

    with pytest.raises(FakeRetryError) as exc_info:
        await locks.acquire_lock(
            FailingRedis(),
            key="lock:doc:1",
            value="owner-a",
            ttl_sec=60,
            fail_open=False,
            retry_defer_sec=9,
        )

    assert exc_info.value.defer == 9


@pytest.mark.asyncio
async def test_tenant_acquire_retries_without_mutating_full_semaphore(monkeypatch: pytest.MonkeyPatch) -> None:
    redis = FakeRedis()
    key = "sem:tenant:t1:doc:1"
    redis.store[key] = "owner-a"
    redis.ttl[key] = 30
    monkeypatch.setattr(locks, "get_retry_exc", lambda: FakeRetryError)

    with pytest.raises(FakeRetryError) as exc_info:
        await locks.tenant_acquire(redis, tenant_id="t1", kind="doc", limit=1, ttl_sec=120, retry_defer_sec=7)

    assert exc_info.value.defer == 7
    assert locks.is_semaphore_busy_retry(exc_info.value) is True
    assert redis.store[key] == "owner-a"
    assert redis.ttl[key] == 30
    assert redis.eval_calls == []


@pytest.mark.asyncio
async def test_tenant_acquire_retries_on_redis_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(locks, "get_retry_exc", lambda: FakeRetryError)

    with pytest.raises(FakeRetryError) as exc_info:
        await locks.tenant_acquire(FailingRedis(), tenant_id="t1", kind="doc", limit=1, ttl_sec=120, retry_defer_sec=6)

    assert exc_info.value.defer == 6
    assert locks.is_semaphore_busy_retry(exc_info.value) is False


@pytest.mark.asyncio
async def test_limit_zero_explicitly_disables_semaphore_even_without_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(locks, "get_retry_exc", lambda: FakeRetryError)

    assert await locks.tenant_acquire(None, tenant_id="t1", kind="doc", limit=0, ttl_sec=120, retry_defer_sec=6) is None


@pytest.mark.asyncio
async def test_dataset_acquire_retries_when_redis_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(locks, "get_retry_exc", lambda: FakeRetryError)

    with pytest.raises(FakeRetryError) as exc_info:
        await locks.dataset_acquire(
            None,
            tenant_id="t1",
            dataset_id="ds1",
            kind="kg",
            limit=1,
            ttl_sec=45,
            retry_defer_sec=4,
        )

    assert exc_info.value.defer == 4


@pytest.mark.asyncio
async def test_tenant_release_deletes_owned_slot_atomically() -> None:
    redis = FakeRedis()
    key = "sem:tenant:t1:doc:1"
    token = "owner-a"
    redis.store[key] = token
    redis.ttl[key] = 120

    await locks.tenant_release(redis, f"{key}|{token}")

    assert key not in redis.store
    assert key not in redis.ttl
    assert redis.eval_calls == [((key,), (token,))]


@pytest.mark.asyncio
async def test_dataset_acquire_and_release_use_owned_slots() -> None:
    redis = FakeRedis()
    key = "sem:dataset:t1:ds1:kg:1"

    acquired = await locks.dataset_acquire(
        redis,
        tenant_id="t1",
        dataset_id="ds1",
        kind="kg",
        limit=2,
        ttl_sec=45,
    )

    assert acquired is not None
    assert acquired.startswith(f"{key}|")
    token = acquired.rsplit("|", 1)[1]
    assert redis.store[key] == token
    assert redis.ttl[key] == 45

    await locks.dataset_release(redis, acquired)

    assert key not in redis.store
    assert redis.eval_calls == [((key,), (token,))]


@pytest.mark.asyncio
async def test_expired_semaphore_owner_cannot_release_replacement() -> None:
    redis = FakeRedis()

    first = await locks.tenant_acquire(redis, tenant_id="t1", kind="doc", limit=1, ttl_sec=120)
    assert first is not None
    slot = first.rsplit("|", 1)[0]

    # Simulate Redis expiring the first lease before another worker takes its slot.
    redis.store.pop(slot)
    redis.ttl.pop(slot)
    second = await locks.tenant_acquire(redis, tenant_id="t1", kind="doc", limit=1, ttl_sec=120)
    assert second is not None

    await locks.tenant_release(redis, first)

    assert redis.store[slot] == second.rsplit("|", 1)[1]


@pytest.mark.asyncio
async def test_connector_job_retries_when_redis_is_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace
    from uuid import uuid4

    from app.tasks import jobs

    tenant_id = uuid4()
    run_id = uuid4()
    run = SimpleNamespace(
        id=run_id,
        tenant_id=tenant_id,
        connector_id="url_batch",
        status="pending",
        error_message=None,
        finished_at=None,
    )
    executed = False

    async def _unexpected_execute(**_kwargs):  # noqa: ANN003, ANN202
        nonlocal executed
        executed = True
        return True

    monkeypatch.setattr(jobs, "SessionLocal", lambda: _RunDB(run), raising=True)
    monkeypatch.setattr(jobs, "execute_connector_run", _unexpected_execute, raising=True)
    monkeypatch.setattr(jobs, "get_retry_exc", lambda: FakeRetryError, raising=True)

    with pytest.raises(FakeRetryError) as exc_info:
        await jobs.connector_run_job({}, str(tenant_id), str(run_id), "member-1")

    assert exc_info.value.defer == 30
    assert executed is False


@pytest.mark.asyncio
async def test_connector_job_marks_failed_on_final_coordination_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace
    from uuid import uuid4

    from app.tasks import jobs

    tenant_id = uuid4()
    run_id = uuid4()
    run = SimpleNamespace(
        id=run_id,
        tenant_id=tenant_id,
        connector_id="url_batch",
        status="pending",
        error_message=None,
        finished_at=None,
    )
    executed = False
    db = _RunDB(run)

    async def _unexpected_execute(**_kwargs):  # noqa: ANN003, ANN202
        nonlocal executed
        executed = True
        return True

    monkeypatch.setattr(jobs, "SessionLocal", lambda: db, raising=True)
    monkeypatch.setattr(jobs, "execute_connector_run", _unexpected_execute, raising=True)
    monkeypatch.setattr(jobs, "get_retry_exc", lambda: FakeRetryError, raising=True)
    monkeypatch.setattr(jobs.settings, "TASK_JOB_MAX_TRIES", 3, raising=False)

    result = await jobs.connector_run_job({"job_try": 3}, str(tenant_id), str(run_id), "member-1")

    assert result["ok"] is False
    assert result["reason"] == "task_coordination_unavailable"
    assert run.status == "failed"
    assert run.error_message == "task_coordination_unavailable"
    assert run.finished_at is not None
    assert db.commits == 1
    assert executed is False


@pytest.mark.asyncio
async def test_document_job_marks_failed_on_final_coordination_retry_without_bypassing_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace
    from uuid import uuid4

    from app.tasks import jobs

    tenant_id = uuid4()
    document_id = uuid4()
    dataset_id = uuid4()
    doc = SimpleNamespace(
        id=document_id,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        doc_metadata={},
        status="pending",
        error_message=None,
    )
    db = _ValueDB(doc)
    observed: dict[str, int] = {}
    processed = False

    async def _tenant_retry(_redis, **kwargs):  # noqa: ANN001, ANN003, ANN202
        observed["tenant_limit"] = int(kwargs["limit"])
        raise FakeRetryError(defer=11)

    async def _unexpected_lock(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        raise AssertionError("should stop after coordination retry")

    async def _unexpected_process(**_kwargs):  # noqa: ANN003, ANN202
        nonlocal processed
        processed = True
        return {"ok": True}

    async def _update_status(_db, _tid, _did, status, _progress, _stage, *, error_message=None):  # noqa: ANN001, ANN202
        doc.status = status
        doc.error_message = error_message

    monkeypatch.setattr(jobs, "SessionLocal", lambda: db, raising=True)
    monkeypatch.setattr(jobs, "get_retry_exc", lambda: FakeRetryError, raising=True)
    monkeypatch.setattr(jobs, "tenant_acquire", _tenant_retry, raising=True)
    monkeypatch.setattr(jobs, "_acquire_task_lock_or_retry", _unexpected_lock, raising=True)
    monkeypatch.setattr(jobs.document_processor, "process_document", _unexpected_process, raising=True)
    monkeypatch.setattr(jobs.document_processor, "_update_status", _update_status, raising=True)
    monkeypatch.setattr(jobs.settings, "TASK_DOCUMENT_JOB_MAX_TRIES", 5, raising=False)
    monkeypatch.setattr(jobs.settings, "TASK_TENANT_MAX_CONCURRENCY_DOC", 2, raising=False)
    monkeypatch.setattr(jobs.settings, "TASK_DATASET_MAX_CONCURRENCY_DOC", 3, raising=False)

    result = await jobs.process_document_job({"job_try": 5, "redis": object()}, str(tenant_id), str(document_id), "member-1")

    assert observed["tenant_limit"] == 2
    assert result["ok"] is False
    assert result["reason"] == "task_coordination_unavailable"
    assert doc.status == "failed"
    assert doc.error_message == "task_coordination_unavailable"
    assert processed is False


@pytest.mark.asyncio
async def test_document_job_propagates_failed_processor_result(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:  # noqa: ANN001
    from types import SimpleNamespace

    from app.tasks import jobs

    tenant_id = uuid4()
    document_id = uuid4()
    source = tmp_path / "document.txt"
    source.write_text("content", encoding="utf-8")
    document = SimpleNamespace(
        id=document_id,
        tenant_id=tenant_id,
        dataset_id=None,
        doc_metadata={},
        file_path=str(source),
    )
    db = _ValueDB(document)

    async def _acquire(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        return None

    async def _lock(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        return True

    async def _release(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        return None

    async def _process(**_kwargs):  # noqa: ANN003, ANN202
        return {"status": "failed", "reason": "retry_cleanup_deferred"}

    monkeypatch.setattr(jobs, "SessionLocal", lambda: db, raising=True)
    monkeypatch.setattr(jobs, "_task_queue_redis_or_retry", lambda *_args, **_kwargs: object(), raising=True)
    monkeypatch.setattr(jobs, "tenant_acquire", _acquire, raising=True)
    monkeypatch.setattr(jobs, "dataset_acquire", _acquire, raising=True)
    monkeypatch.setattr(jobs, "_acquire_task_lock_or_retry", _lock, raising=True)
    monkeypatch.setattr(jobs, "release_lock", _release, raising=True)
    monkeypatch.setattr(jobs, "dataset_release", _release, raising=True)
    monkeypatch.setattr(jobs, "tenant_release", _release, raising=True)
    monkeypatch.setattr(jobs.document_processor, "process_document", _process, raising=True)

    result = await jobs.process_document_job(
        {"job_try": 1, "redis": object()},
        str(tenant_id),
        str(document_id),
        "member-1",
    )

    assert result["ok"] is False
    assert result["reason"] == "retry_cleanup_deferred"
    assert result["progress"] == {"stage": "failed", "done": 0, "total": 1}


@pytest.mark.asyncio
async def test_dataset_profile_scan_marks_failed_on_final_coordination_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace
    from uuid import uuid4

    from app.tasks import jobs

    tenant_id = uuid4()
    dataset_id = uuid4()
    run_id = uuid4()
    run = SimpleNamespace(
        id=run_id,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        status="pending",
        error_message=None,
        finished_at=None,
    )
    executed = False
    db = _RunDB(run)

    def _unexpected_scan(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        nonlocal executed
        executed = True
        return {"ok": True}

    monkeypatch.setattr(jobs, "SessionLocal", lambda: db, raising=True)
    monkeypatch.setattr(jobs, "run_dataset_profile_deep_scan", _unexpected_scan, raising=True)
    monkeypatch.setattr(jobs, "get_retry_exc", lambda: FakeRetryError, raising=True)
    monkeypatch.setattr(jobs.settings, "TASK_JOB_MAX_TRIES", 3, raising=False)

    result = await jobs.dataset_profile_scan_job(
        {"job_try": 3},
        str(tenant_id),
        str(dataset_id),
        str(run_id),
        "member-1",
    )

    assert result["ok"] is False
    assert result["reason"] == "task_coordination_unavailable"
    assert run.status == "failed"
    assert run.error_message == "task_coordination_unavailable"
    assert run.finished_at is not None
    assert db.commits == 1
    assert executed is False


@pytest.mark.asyncio
async def test_dataset_precheck_scan_marks_failed_on_final_coordination_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace
    from uuid import uuid4

    from app.tasks import jobs

    tenant_id = uuid4()
    dataset_id = uuid4()
    run_id = uuid4()
    run = SimpleNamespace(
        id=run_id,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        status="pending",
        error_message=None,
        finished_at=None,
    )
    executed = False
    db = _RunDB(run)

    def _unexpected_scan(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        nonlocal executed
        executed = True
        return {"ok": True}

    monkeypatch.setattr(jobs, "SessionLocal", lambda: db, raising=True)
    monkeypatch.setattr(jobs, "run_dataset_precheck_scan", _unexpected_scan, raising=True)
    monkeypatch.setattr(jobs, "get_retry_exc", lambda: FakeRetryError, raising=True)
    monkeypatch.setattr(jobs.settings, "TASK_JOB_MAX_TRIES", 3, raising=False)

    result = await jobs.dataset_precheck_scan_job(
        {"job_try": 3},
        str(tenant_id),
        str(dataset_id),
        str(run_id),
        "member-1",
    )

    assert result["ok"] is False
    assert result["reason"] == "task_coordination_unavailable"
    assert run.status == "failed"
    assert run.error_message == "task_coordination_unavailable"
    assert run.finished_at is not None
    assert db.commits == 1
    assert executed is False


@pytest.mark.asyncio
async def test_evidence_repair_job_marks_failed_on_final_coordination_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.tasks import jobs

    tenant_id = uuid4()
    suite_id = uuid4()

    monkeypatch.setattr(jobs, "SessionLocal", lambda: _ValueDB(None), raising=True)
    monkeypatch.setattr(jobs, "get_retry_exc", lambda: FakeRetryError, raising=True)
    monkeypatch.setattr(jobs.settings, "TASK_JOB_MAX_TRIES", 3, raising=False)

    result = await jobs.evidence_reference_sources_repair_job(
        {"job_try": 3},
        str(tenant_id),
        str(suite_id),
        "member-1",
        False,
        False,
        False,
        10,
        10,
        10,
    )

    assert result["ok"] is False
    assert result["reason"] == "task_coordination_unavailable"


@pytest.mark.asyncio
async def test_extract_kg_job_marks_failed_on_final_coordination_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.tasks import jobs

    tenant_id = uuid4()
    document_id = uuid4()

    monkeypatch.setattr(jobs, "SessionLocal", lambda: _ValueDB(None), raising=True)
    monkeypatch.setattr(jobs, "get_retry_exc", lambda: FakeRetryError, raising=True)
    monkeypatch.setattr(jobs.settings, "TASK_KG_JOB_MAX_TRIES", 3, raising=False)

    result = await jobs.extract_kg_job(
        {"job_try": 3},
        str(tenant_id),
        str(document_id),
        "member-1",
    )

    assert result["ok"] is False
    assert result["reason"] == "task_coordination_unavailable"


@pytest.mark.asyncio
async def test_extract_kg_job_keeps_concurrency_limits_on_final_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from app.tasks import jobs

    tenant_id = uuid4()
    document_id = uuid4()
    dataset_id = uuid4()
    doc = SimpleNamespace(
        id=document_id,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        status="completed",
        doc_metadata={},
    )
    observed: dict[str, int] = {}

    async def _tenant_acquire(_redis, **kwargs):  # noqa: ANN001, ANN003, ANN202
        observed["tenant_limit"] = int(kwargs["limit"])
        return None

    async def _dataset_acquire(_redis, **kwargs):  # noqa: ANN001, ANN003, ANN202
        observed["dataset_limit"] = int(kwargs["limit"])
        raise FakeRetryError(defer=11)

    monkeypatch.setattr(jobs, "SessionLocal", lambda: _ValueDB(doc), raising=True)
    monkeypatch.setattr(jobs, "get_retry_exc", lambda: FakeRetryError, raising=True)
    monkeypatch.setattr(jobs, "tenant_acquire", _tenant_acquire, raising=True)
    monkeypatch.setattr(jobs, "dataset_acquire", _dataset_acquire, raising=True)
    monkeypatch.setattr(jobs, "is_semaphore_busy_retry", lambda _exc: True, raising=True)
    monkeypatch.setattr(jobs.settings, "TASK_KG_JOB_MAX_TRIES", 3, raising=False)
    monkeypatch.setattr(jobs.settings, "TASK_TENANT_MAX_CONCURRENCY_KG", 2, raising=False)
    monkeypatch.setattr(jobs.settings, "TASK_DATASET_MAX_CONCURRENCY_KG", 4, raising=False)

    result = await jobs.extract_kg_job(
        {"job_try": 3, "redis": object()},
        str(tenant_id),
        str(document_id),
        "member-1",
    )

    assert result["ok"] is False
    assert result["reason"] == "task_concurrency_busy"
    assert observed == {"tenant_limit": 2, "dataset_limit": 4}


@pytest.mark.asyncio
async def test_extract_kg_job_fails_closed_when_selected_pipeline_has_no_matching_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from types import SimpleNamespace

    from app.tasks import jobs

    tenant_id = uuid4()
    document_id = uuid4()
    document = SimpleNamespace(
        id=document_id,
        tenant_id=tenant_id,
        dataset_id=None,
        status="completed",
        doc_metadata={"active_pipeline_hash": "pipe-b", "pipeline_hash": "pipe-a"},
    )
    chunks = [
        SimpleNamespace(id=uuid4(), doc_metadata={"pipeline_hash": "pipe-a", "doc_pipeline_key": f"{document_id}:pipe-a"}),
        SimpleNamespace(id=uuid4(), doc_metadata={"pipeline_hash": "pipe-a", "doc_pipeline_key": f"{document_id}:pipe-a"}),
    ]
    db = _KGDB(document=document, chunks=chunks)

    async def _tenant_acquire(_redis, **_kwargs):  # noqa: ANN001, ANN003, ANN202
        return None

    async def _dataset_acquire(_redis, **_kwargs):  # noqa: ANN001, ANN003, ANN202
        return None

    async def _acquire(_redis, **_kwargs):  # noqa: ANN001, ANN003, ANN202
        return True

    async def _release(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        return None

    monkeypatch.setattr(jobs, "SessionLocal", lambda: db, raising=True)
    monkeypatch.setattr(jobs, "_task_queue_redis_or_retry", lambda *_args, **_kwargs: object(), raising=True)
    monkeypatch.setattr(jobs, "tenant_acquire", _tenant_acquire, raising=True)
    monkeypatch.setattr(jobs, "dataset_acquire", _dataset_acquire, raising=True)
    monkeypatch.setattr(jobs, "_acquire_task_lock_or_retry", _acquire, raising=True)
    monkeypatch.setattr(jobs, "release_lock", _release, raising=True)
    monkeypatch.setattr(jobs, "dataset_release", _release, raising=True)
    monkeypatch.setattr(jobs, "tenant_release", _release, raising=True)
    monkeypatch.setattr(
        "app.services.pipeline_config.resolve_pipeline_effective",
        lambda **_kwargs: SimpleNamespace(kg_python_plugin="", kg_python_params={}),
        raising=True,
    )
    monkeypatch.setattr("app.services.pipeline_config.build_indexing_options", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(
        "app.rag.pipeline_plugins.registry.derive_registered_stage_plugin_ref",
        lambda *_args, **_kwargs: "",
        raising=True,
    )
    monkeypatch.setattr(
        "app.rag.kg.pipeline.extract_events",
        lambda *_args, **_kwargs: pytest.fail("extract_events must not run for mismatched pipeline chunks"),
        raising=True,
    )

    result = await jobs.extract_kg_job(
        {"job_try": 1, "redis": object()},
        str(tenant_id),
        str(document_id),
        "member-1",
    )

    assert result["ok"] is False
    assert result["reason"] == "pipeline_chunks_not_found"
    assert result["pipeline_hash"] == "pipe-b"


@pytest.mark.asyncio
async def test_extract_kg_job_invalidates_dataset_cache_after_success(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from app.rag.kg.extraction_job_options import (
        build_kg_extraction_job_options,
        kg_extraction_job_options_fingerprint,
    )
    from app.tasks import jobs

    tenant_id = uuid4()
    document_id = uuid4()
    dataset_id = uuid4()
    document = SimpleNamespace(
        id=document_id,
        tenant_id=tenant_id,
        dataset_id=dataset_id,
        status="completed",
        doc_metadata={"active_pipeline_hash": "pipe-a", "pipeline_hash": "pipe-a"},
    )
    chunks = [
        SimpleNamespace(id=uuid4(), doc_metadata={"pipeline_hash": "pipe-a", "doc_pipeline_key": f"{document_id}:pipe-a"}),
    ]
    dataset = SimpleNamespace(dataset_metadata={})
    db = _KGDB(document=document, chunks=chunks, dataset=dataset)
    prompt_template_id = uuid4()
    effective_options = build_kg_extraction_job_options(
        pipeline_hash="pipe-a",
        prompt_template_id=prompt_template_id,
        prompt_template_key="prompt-a",
        prompt_ab_experiment_key="experiment-a",
        extraction_backend="hybrid",
        kg_python_plugin="plugin:queued",
        kg_python_params={"threshold": 0.75},
        replace_existing=True,
        prune_orphan_entities=False,
        extract_relations=True,
        extract_skills=False,
    )
    fingerprint = kg_extraction_job_options_fingerprint(effective_options)
    extract_calls: list[tuple[list[object], dict[str, object]]] = []
    acquired_locks: list[str] = []
    cache_invalidations: list[tuple[object, object]] = []

    async def _tenant_acquire(_redis, **_kwargs):  # noqa: ANN001, ANN003, ANN202
        return None

    async def _dataset_acquire(_redis, **_kwargs):  # noqa: ANN001, ANN003, ANN202
        return None

    async def _acquire(_redis, **kwargs):  # noqa: ANN001, ANN003, ANN202
        acquired_locks.append(str(kwargs["key"]))
        return True

    async def _release(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        return None

    async def _extract_events(chunk_ids, **kwargs):  # noqa: ANN001, ANN202
        extract_calls.append((list(chunk_ids), dict(kwargs)))
        return [SimpleNamespace(id=uuid4()), SimpleNamespace(id=uuid4())]

    monkeypatch.setattr(jobs, "SessionLocal", lambda: db, raising=True)
    monkeypatch.setattr(jobs, "_task_queue_redis_or_retry", lambda *_args, **_kwargs: object(), raising=True)
    monkeypatch.setattr(jobs, "tenant_acquire", _tenant_acquire, raising=True)
    monkeypatch.setattr(jobs, "dataset_acquire", _dataset_acquire, raising=True)
    monkeypatch.setattr(jobs, "_acquire_task_lock_or_retry", _acquire, raising=True)
    monkeypatch.setattr(jobs, "release_lock", _release, raising=True)
    monkeypatch.setattr(jobs, "dataset_release", _release, raising=True)
    monkeypatch.setattr(jobs, "tenant_release", _release, raising=True)
    monkeypatch.setattr(
        "app.services.pipeline_config.resolve_pipeline_effective",
        lambda **_kwargs: SimpleNamespace(kg_python_plugin="plugin:changed", kg_python_params={"changed": True}),
        raising=True,
    )
    monkeypatch.setattr("app.services.pipeline_config.build_indexing_options", lambda *_a, **_k: None, raising=True)
    monkeypatch.setattr(
        "app.rag.pipeline_plugins.registry.derive_registered_stage_plugin_ref",
        lambda *_args, **_kwargs: "",
        raising=True,
    )
    monkeypatch.setattr("app.rag.kg.pipeline.extract_events", _extract_events, raising=True)
    monkeypatch.setattr(
        "app.services.corpus_cache_tokens.invalidate_dataset_cache_namespace",
        lambda _db, *, tenant_id, dataset_id: cache_invalidations.append((tenant_id, dataset_id)) or {"dataset_id": str(dataset_id)},
        raising=True,
    )

    result = await jobs.extract_kg_job(
        {"job_try": 1, "redis": object()},
        str(tenant_id),
        str(document_id),
        "member-1",
        False,
        True,
        False,
        True,
        "pipe-a",
        effective_options,
    )

    assert result["ok"] is True
    assert result["event_count"] == 2
    assert result["cache_invalidation"] == {"dataset_id": str(dataset_id)}
    assert extract_calls[0][0] == [chunks[0].id]
    assert extract_calls[0][1]["prompt_template_id"] == prompt_template_id
    assert extract_calls[0][1]["prompt_template_key"] == "prompt-a"
    assert extract_calls[0][1]["prompt_ab_experiment_key"] == "experiment-a"
    assert extract_calls[0][1]["extraction_backend"] == "hybrid"
    assert extract_calls[0][1]["kg_python_plugin"] == "plugin:queued"
    assert extract_calls[0][1]["kg_python_params"] == {"threshold": 0.75}
    assert extract_calls[0][1]["replace_existing"] is True
    assert extract_calls[0][1]["prune_orphan_entities"] is False
    assert extract_calls[0][1]["extract_relations"] is True
    assert extract_calls[0][1]["extract_skills"] is False
    assert acquired_locks == [f"lock:kg:{tenant_id}:{document_id}:pipe-a:{fingerprint}"]
    assert cache_invalidations == [(tenant_id, dataset_id)]
    assert db.commits >= 1


@pytest.mark.asyncio
async def test_rebuild_indexes_job_scopes_reconcile_to_document(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.tasks import jobs
    from app.types.indexing import IndexKind

    tenant_id = uuid4()
    document_id = uuid4()
    calls: list[dict[str, object]] = []

    async def _tenant_acquire(_redis, **_kwargs):  # noqa: ANN001, ANN003, ANN202
        return None

    async def _acquire(_redis, **_kwargs):  # noqa: ANN001, ANN003, ANN202
        return True

    async def _release(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        return None

    class _Indexer:
        def __init__(self, _db) -> None:  # noqa: ANN001
            pass

        def rebuild_tenant(self, **kwargs) -> None:  # noqa: ANN003
            calls.append(dict(kwargs))

    monkeypatch.setattr(jobs, "SessionLocal", lambda: _ValueDB(None), raising=True)
    monkeypatch.setattr(jobs, "_task_queue_redis_or_retry", lambda *_args, **_kwargs: object(), raising=True)
    monkeypatch.setattr(jobs, "tenant_acquire", _tenant_acquire, raising=True)
    monkeypatch.setattr(jobs, "_acquire_task_lock_or_retry", _acquire, raising=True)
    monkeypatch.setattr(jobs, "release_lock", _release, raising=True)
    monkeypatch.setattr(jobs, "tenant_release", _release, raising=True)
    monkeypatch.setattr("app.services.indexer.Indexer", _Indexer, raising=True)

    result = await jobs.rebuild_indexes_job(
        {"job_try": 1, "redis": object()},
        str(tenant_id),
        "member-1",
        str(document_id),
    )

    assert result["ok"] is True
    assert result["document_id"] == str(document_id)
    assert calls == [{"tenant_id": tenant_id, "document_ids": [document_id], "kinds": [IndexKind.CHUNK]}]


@pytest.mark.asyncio
async def test_rebuild_job_marks_failed_on_final_coordination_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.tasks import jobs

    tenant_id = uuid4()

    monkeypatch.setattr(jobs, "SessionLocal", lambda: _ValueDB(None), raising=True)
    monkeypatch.setattr(jobs, "get_retry_exc", lambda: FakeRetryError, raising=True)
    monkeypatch.setattr(jobs.settings, "TASK_JOB_MAX_TRIES", 3, raising=False)

    result = await jobs.rebuild_indexes_job({"job_try": 3}, str(tenant_id), "member-1")

    assert result["ok"] is False
    assert result["reason"] == "task_coordination_unavailable"


def test_mark_run_failed_rolls_back_when_terminal_state_cannot_be_persisted() -> None:
    from types import SimpleNamespace

    from app.tasks import jobs

    run = SimpleNamespace(status="pending", error_message=None, finished_at=None)
    db = _FailingCommitDB(run)

    with pytest.raises(RuntimeError, match="failed to persist task run terminal state"):
        jobs._mark_run_failed(db, run, reason="task_coordination_unavailable")

    assert db.rollbacks == 1


@pytest.mark.asyncio
async def test_document_terminal_state_rolls_back_when_status_update_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.tasks import jobs

    db = _RunDB(None)

    async def _fail_status_update(*_args, **_kwargs):  # noqa: ANN002, ANN003, ANN202
        raise SQLAlchemyError("commit failed")

    monkeypatch.setattr(jobs.document_processor, "_update_status", _fail_status_update, raising=True)
    monkeypatch.setattr(jobs.settings, "TASK_DOCUMENT_JOB_MAX_TRIES", 1, raising=False)

    with pytest.raises(RuntimeError, match="failed to persist document task terminal state"):
        await jobs._mark_document_failed_on_exhausted_retry(
            ctx={"job_try": 1},
            db=db,
            tenant_id=uuid4(),
            document_id=uuid4(),
            reason="task_coordination_unavailable",
        )

    assert db.rollbacks == 1
