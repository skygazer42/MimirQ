import asyncio
import multiprocessing
import threading
import time

import pytest


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.ttl: dict[str, int] = {}
        self.set_calls: list[tuple[str, str, int | None, bool]] = []
        self.eval_calls: list[tuple[str, str, str]] = []

    def set(self, key: str, value: str, *, ex: int | None = None, nx: bool = False) -> bool:
        self.set_calls.append((key, value, ex, nx))
        if nx and key in self.store:
            return False
        self.store[key] = value
        if ex is not None:
            self.ttl[key] = int(ex)
        return True

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def eval(self, _script: str, numkeys: int, *values: str) -> int:
        assert numkeys == 1
        key = values[0]
        owner = values[1]
        op = "extend" if "EXPIRE" in _script else "release"
        self.eval_calls.append((op, key, owner))
        if self.store.get(key) != owner:
            return 0
        if op == "extend":
            self.ttl[key] = int(values[2])
            return 1
        if op == "release":
            self.store.pop(key, None)
            self.ttl.pop(key, None)
            return 1
        return 0


class _BrokenRedis(_FakeRedis):
    def set(self, key: str, value: str, *, ex: int | None = None, nx: bool = False) -> bool:  # noqa: ARG002
        raise RuntimeError("redis unavailable")


class _SharedRedis:
    def __init__(self, slots, lock) -> None:  # noqa: ANN001
        self.slots = slots
        self.lock = lock

    @staticmethod
    def _slot_index(key: str) -> int:
        return int(key.rsplit(":", 1)[-1]) - 1

    @staticmethod
    def _owner_token(owner: str) -> int:
        return int(owner[:16], 16) or 1

    def set(self, key: str, value: str, *, ex: int | None = None, nx: bool = False) -> bool:  # noqa: ARG002
        with self.lock:
            index = self._slot_index(key)
            if nx and self.slots[index] != 0:
                return False
            self.slots[index] = self._owner_token(value)
            return True

    def get(self, key: str) -> str | None:
        with self.lock:
            token = self.slots[self._slot_index(key)]
            return str(token) if token else None

    def eval(self, script: str, numkeys: int, *values: str) -> int:
        assert numkeys == 1
        key, owner = values[:2]
        with self.lock:
            index = self._slot_index(key)
            if self.slots[index] != self._owner_token(owner):
                return 0
            if "EXPIRE" not in script:
                self.slots[index] = 0
            return 1


def _enable_distributed(  # noqa: ANN001
    monkeypatch: pytest.MonkeyPatch,
    limiter,
    redis,
    *,
    local_limit: int = 1,
    distributed_limit: int = 1,
    admission_timeout_sec: float = 0.2,
) -> None:
    monkeypatch.setattr(limiter.settings, "RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_ENABLED", True, raising=False)
    monkeypatch.setattr(
        limiter.settings,
        "RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_MAX_CONCURRENCY",
        distributed_limit,
        raising=False,
    )
    monkeypatch.setattr(limiter.settings, "RAG_RETRIEVAL_OFFLOAD_MAX_CONCURRENCY", local_limit, raising=False)
    monkeypatch.setattr(
        limiter.settings,
        "RAG_RETRIEVAL_ADMISSION_TIMEOUT_SEC",
        admission_timeout_sec,
        raising=False,
    )
    monkeypatch.setattr(limiter, "_get_redis_client", lambda: redis, raising=True)
    monkeypatch.setattr(limiter, "_invalidate_redis_client", lambda: None, raising=True)
    monkeypatch.setattr(limiter, "_gate", None, raising=False)
    monkeypatch.setattr(limiter, "_gate_limit", 0, raising=False)


@pytest.mark.asyncio
async def test_distributed_retrieval_admission_blocks_without_process_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.rag_runtime_limiter as limiter

    redis = _FakeRedis()
    first_started = threading.Event()
    release_first = threading.Event()
    second_started = threading.Event()
    _enable_distributed(monkeypatch, limiter, redis)
    monkeypatch.setattr(limiter, "_get_gate", lambda _limit: None, raising=True)

    def first_work() -> None:
        first_started.set()
        assert release_first.wait(timeout=2)

    first_task = asyncio.create_task(limiter.run_blocking_retrieval_call(first_work))
    assert await asyncio.to_thread(first_started.wait, 1)

    second_task = asyncio.create_task(limiter.run_blocking_retrieval_call(second_started.set))
    await asyncio.sleep(0.05)
    assert second_started.is_set() is False

    release_first.set()
    await asyncio.gather(first_task, second_task)
    assert second_started.is_set() is True
    assert redis.store == {}


@pytest.mark.asyncio
async def test_distributed_retrieval_admission_keeps_slot_after_outer_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.rag_runtime_limiter as limiter

    redis = _FakeRedis()
    first_started = threading.Event()
    release_first = threading.Event()
    second_started = threading.Event()
    _enable_distributed(monkeypatch, limiter, redis)
    monkeypatch.setattr(limiter, "_get_gate", lambda _limit: None, raising=True)

    def first_work() -> None:
        first_started.set()
        assert release_first.wait(timeout=2)

    first_task = asyncio.create_task(limiter.run_blocking_retrieval_call(first_work))
    assert await asyncio.to_thread(first_started.wait, 1)

    second_task = asyncio.create_task(limiter.run_blocking_retrieval_call(second_started.set))
    await asyncio.sleep(0.05)
    first_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first_task

    await asyncio.sleep(0.05)
    assert second_started.is_set() is False

    release_first.set()
    await second_task
    assert second_started.is_set() is True
    assert redis.store == {}


@pytest.mark.asyncio
async def test_distributed_retrieval_admission_releases_slot_when_local_gate_times_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.rag_runtime_limiter as limiter

    redis = _FakeRedis()
    gate = threading.BoundedSemaphore(1)
    assert gate.acquire(blocking=False) is True
    _enable_distributed(monkeypatch, limiter, redis)
    monkeypatch.setattr(limiter, "_get_gate", lambda _limit: gate, raising=True)

    try:
        with pytest.raises(limiter.RetrievalAdmissionTimeoutError):
            await limiter.run_blocking_retrieval_call(lambda: None)
    finally:
        gate.release()

    assert redis.set_calls == []
    assert redis.store == {}
    assert redis.eval_calls == []


@pytest.mark.asyncio
async def test_distributed_retrieval_admission_releases_slot_when_local_gate_wait_is_cancelled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.rag_runtime_limiter as limiter

    redis = _FakeRedis()
    gate = threading.BoundedSemaphore(1)
    assert gate.acquire(blocking=False) is True
    work_started = threading.Event()
    _enable_distributed(monkeypatch, limiter, redis)
    monkeypatch.setattr(limiter, "_get_gate", lambda _limit: gate, raising=True)

    task = asyncio.create_task(limiter.run_blocking_retrieval_call(work_started.set))
    await asyncio.sleep(0.05)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    gate.release()
    assert work_started.is_set() is False
    assert redis.set_calls == []
    assert redis.store == {}
    assert redis.eval_calls == []


@pytest.mark.asyncio
async def test_distributed_retrieval_admission_heartbeats_until_worker_release(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.rag_runtime_limiter as limiter

    redis = _FakeRedis()
    started = threading.Event()
    release_work = threading.Event()
    extend_calls: list[str] = []
    extended = threading.Event()
    original_extend = limiter.extend_redis_lease
    _enable_distributed(monkeypatch, limiter, redis)
    monkeypatch.setattr(limiter, "_get_gate", lambda _limit: None, raising=True)
    monkeypatch.setattr(
        limiter,
        "_distributed_admission_lease_renew_interval_sec",
        lambda _ttl_sec: 0.01,
        raising=True,
    )

    def _extend(client, key: str, *, value: str, ttl_sec: int) -> bool:  # noqa: ANN001
        extend_calls.append(key)
        extended.set()
        return bool(original_extend(client, key, value=value, ttl_sec=ttl_sec))

    monkeypatch.setattr(limiter, "extend_redis_lease", _extend, raising=True)

    def work() -> None:
        started.set()
        assert release_work.wait(timeout=2)

    task = asyncio.create_task(limiter.run_blocking_retrieval_call(work))
    assert await asyncio.to_thread(started.wait, 1) is True
    assert await asyncio.to_thread(extended.wait, 0.5) is True

    release_work.set()
    await task
    count_after_release = len(extend_calls)
    time.sleep(0.05)

    assert count_after_release >= 1
    assert len(extend_calls) == count_after_release
    assert redis.store == {}


def test_distributed_retrieval_admission_slot_keys_do_not_encode_capacity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.rag_runtime_limiter as limiter

    redis = _FakeRedis()
    _enable_distributed(monkeypatch, limiter, redis, distributed_limit=4)
    monkeypatch.setattr(limiter, "_get_gate", lambda _limit: None, raising=True)

    assert limiter.run_blocking_retrieval_call_sync(lambda: "ok") == "ok"
    assert redis.set_calls[0][0] == "ragadm:1"


def test_distributed_retrieval_admission_zero_global_limit_inherits_local_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.rag_runtime_limiter as limiter

    redis = _FakeRedis()
    _enable_distributed(monkeypatch, limiter, redis, local_limit=3, distributed_limit=0)

    leases = [
        limiter._try_acquire_distributed_admission_slot(limit=3, timeout_sec=0.2)[0],
        limiter._try_acquire_distributed_admission_slot(limit=3, timeout_sec=0.2)[0],
        limiter._try_acquire_distributed_admission_slot(limit=3, timeout_sec=0.2)[0],
    ]
    blocked, degraded = limiter._try_acquire_distributed_admission_slot(limit=3, timeout_sec=0.2)

    try:
        assert [lease.key for lease in leases if lease is not None] == ["ragadm:1", "ragadm:2", "ragadm:3"]
        assert all(lease is not None for lease in leases)
        assert blocked is None
        assert degraded is False
    finally:
        for lease in leases:
            limiter._release_distributed_admission_slot(lease)


def test_distributed_backend_budget_uses_separate_global_slots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.rag_runtime_limiter as limiter

    redis = _FakeRedis()
    _enable_distributed(monkeypatch, limiter, redis, local_limit=2, distributed_limit=2)
    monkeypatch.setattr(limiter.settings, "RAG_VECTOR_SHARD_GLOBAL_MAX_CONCURRENCY", 1, raising=False)
    monkeypatch.setattr(limiter, "_backend_gate", None, raising=False)
    monkeypatch.setattr(limiter, "_backend_gate_limit", 0, raising=False)

    assert limiter.run_with_retrieval_backend_budget_sync(lambda: "ok") == "ok"

    assert redis.set_calls[0][0] == "ragadm:backend:1"
    assert redis.store == {}


@pytest.mark.skipif("fork" not in multiprocessing.get_all_start_methods(), reason="requires fork semantics")
def test_distributed_backend_budget_is_shared_across_processes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.rag_runtime_limiter as limiter

    context = multiprocessing.get_context("fork")
    slots = context.Array("Q", 2, lock=False)
    redis = _SharedRedis(slots, context.Lock())
    active = context.Value("i", 0)
    max_active = context.Value("i", 0)
    start = context.Event()

    monkeypatch.setattr(limiter.settings, "RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_ENABLED", True, raising=False)
    monkeypatch.setattr(
        limiter.settings, "RAG_RETRIEVAL_DISTRIBUTED_ADMISSION_PREFIX", "ragadm-multiprocess", raising=False
    )
    monkeypatch.setattr(limiter.settings, "RAG_RETRIEVAL_ADMISSION_TIMEOUT_SEC", 2.0, raising=False)
    monkeypatch.setattr(limiter.settings, "RAG_RETRIEVAL_OFFLOAD_MAX_CONCURRENCY", 2, raising=False)
    monkeypatch.setattr(limiter.settings, "RAG_VECTOR_SHARD_GLOBAL_MAX_CONCURRENCY", 2, raising=False)
    monkeypatch.setattr(limiter, "_get_redis_client", lambda: redis, raising=True)
    monkeypatch.setattr(limiter, "_invalidate_redis_client", lambda: None, raising=True)
    monkeypatch.setattr(limiter, "_backend_gate", None, raising=False)
    monkeypatch.setattr(limiter, "_backend_gate_limit", 0, raising=False)

    def _worker() -> None:
        start.wait(timeout=2)

        def _backend_call() -> None:
            with active.get_lock():
                active.value += 1
                max_active.value = max(max_active.value, active.value)
            time.sleep(0.15)
            with active.get_lock():
                active.value -= 1

        limiter.run_with_retrieval_backend_budget_sync(_backend_call, timeout_sec=2.0)

    processes = [context.Process(target=_worker) for _ in range(4)]
    for process in processes:
        process.start()
    start.set()
    for process in processes:
        process.join(timeout=5)
        assert process.exitcode == 0

    assert max_active.value <= 2
    assert list(slots) == [0, 0]


def test_sync_distributed_wait_releases_local_gate_between_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.rag_runtime_limiter as limiter

    redis = _FakeRedis()
    events: list[str] = []
    attempts = 0
    _enable_distributed(monkeypatch, limiter, redis, local_limit=1, distributed_limit=1)

    class _TrackingGate:
        def acquire(self, *args, **kwargs) -> bool:  # noqa: ANN002, ANN003
            events.append("local_acquire")
            return True

        def release(self) -> None:
            events.append("local_release")

    def _try_slot(**_kwargs):  # noqa: ANN003, ANN202
        nonlocal attempts
        attempts += 1
        events.append(f"distributed_attempt_{attempts}")
        return (None, False) if attempts == 1 else (None, True)

    monkeypatch.setattr(limiter, "_get_gate", lambda _limit: _TrackingGate(), raising=True)
    monkeypatch.setattr(limiter, "_try_acquire_distributed_admission_slot", _try_slot, raising=True)
    monkeypatch.setattr(limiter.time, "sleep", lambda _delay: events.append("wait"), raising=True)

    assert limiter.run_blocking_retrieval_call_sync(lambda: events.append("work") or "ok") == "ok"
    assert events.index("local_release") < events.index("wait")
    assert events.count("local_acquire") == 2


@pytest.mark.asyncio
async def test_async_distributed_wait_releases_local_gate_between_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.rag_runtime_limiter as limiter

    redis = _FakeRedis()
    events: list[str] = []
    attempts = 0
    _enable_distributed(monkeypatch, limiter, redis, local_limit=1, distributed_limit=1)

    class _TrackingGate:
        def acquire(self, *args, **kwargs) -> bool:  # noqa: ANN002, ANN003
            events.append("local_acquire")
            return True

        def release(self) -> None:
            events.append("local_release")

    def _try_slot(**_kwargs):  # noqa: ANN003, ANN202
        nonlocal attempts
        attempts += 1
        events.append(f"distributed_attempt_{attempts}")
        return (None, False) if attempts == 1 else (None, True)

    async def _sleep(_delay: float) -> None:
        events.append("wait")

    monkeypatch.setattr(limiter, "_get_gate", lambda _limit: _TrackingGate(), raising=True)
    monkeypatch.setattr(limiter, "_try_acquire_distributed_admission_slot", _try_slot, raising=True)
    monkeypatch.setattr(limiter.asyncio, "sleep", _sleep, raising=True)

    assert await limiter.run_blocking_retrieval_call(lambda: events.append("work") or "ok") == "ok"
    assert events.index("local_release") < events.index("wait")
    assert events.count("local_acquire") == 2


def test_explicit_global_limit_works_when_local_gate_is_unlimited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.rag_runtime_limiter as limiter

    redis = _FakeRedis()
    _enable_distributed(monkeypatch, limiter, redis, local_limit=0, distributed_limit=2)

    assert limiter._distributed_admission_enabled(0) is True
    lease, degraded = limiter._try_acquire_distributed_admission_slot(limit=0, timeout_sec=0.2)
    try:
        assert lease is not None
        assert lease.key == "ragadm:1"
        assert degraded is False
    finally:
        limiter._release_distributed_admission_slot(lease)


def test_distributed_retrieval_admission_nested_sync_call_does_not_double_acquire(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.rag_runtime_limiter as limiter

    redis = _FakeRedis()
    _enable_distributed(monkeypatch, limiter, redis)
    monkeypatch.setattr(limiter, "_get_gate", lambda _limit: None, raising=True)

    def inner() -> str:
        return "inner"

    def outer() -> str:
        return limiter.run_blocking_retrieval_call_sync(inner)

    assert limiter.run_blocking_retrieval_call_sync(outer) == "inner"
    assert len(redis.set_calls) == 1
    assert redis.store == {}


@pytest.mark.asyncio
async def test_distributed_retrieval_admission_degrades_to_local_gate_when_redis_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.rag_runtime_limiter as limiter

    invalidations = 0
    redis = _BrokenRedis()
    first_started = threading.Event()
    release_first = threading.Event()
    second_started = threading.Event()
    first_metrics: dict[str, object] = {}
    second_metrics: dict[str, object] = {}
    _enable_distributed(monkeypatch, limiter, redis)

    def mark_invalidated() -> None:
        nonlocal invalidations
        invalidations += 1

    monkeypatch.setattr(limiter, "_invalidate_redis_client", mark_invalidated, raising=True)

    def first_work() -> None:
        first_started.set()
        assert release_first.wait(timeout=2)

    first_task = asyncio.create_task(limiter.run_blocking_retrieval_call(first_work, runtime_metrics=first_metrics))
    assert await asyncio.to_thread(first_started.wait, 1)

    second_task = asyncio.create_task(
        limiter.run_blocking_retrieval_call(second_started.set, runtime_metrics=second_metrics)
    )
    await asyncio.sleep(0.05)
    assert second_started.is_set() is False

    release_first.set()
    await asyncio.gather(first_task, second_task)

    assert invalidations >= 1
    assert first_metrics["rag_offload_limit"] == 1
    assert second_metrics["rag_offload_limit"] == 1
    assert first_metrics["rag_distributed_admission_enabled"] is True
    assert second_metrics["rag_distributed_admission_enabled"] is True
    assert second_started.is_set() is True


def test_distributed_retrieval_admission_releases_slot_after_sync_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.rag_runtime_limiter as limiter

    redis = _FakeRedis()
    _enable_distributed(monkeypatch, limiter, redis)
    monkeypatch.setattr(limiter, "_get_gate", lambda _limit: None, raising=True)

    def boom() -> None:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        limiter.run_blocking_retrieval_call_sync(boom)

    assert redis.store == {}
    assert limiter.run_blocking_retrieval_call_sync(lambda: "ok") == "ok"


def test_retrieval_backend_budget_is_globally_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.rag_runtime_limiter as limiter

    first_started = threading.Event()
    release_first = threading.Event()
    second_started = threading.Event()
    monkeypatch.setattr(limiter.settings, "RAG_VECTOR_SHARD_GLOBAL_MAX_CONCURRENCY", 1, raising=False)
    monkeypatch.setattr(limiter.settings, "RAG_RETRIEVAL_ADMISSION_TIMEOUT_SEC", 0.5, raising=False)
    monkeypatch.setattr(limiter, "_backend_gate", None, raising=False)
    monkeypatch.setattr(limiter, "_backend_gate_limit", 0, raising=False)

    def first_work() -> str:
        first_started.set()
        assert release_first.wait(timeout=2)
        return "first"

    first_result: list[str] = []
    second_result: list[str] = []

    first_thread = threading.Thread(
        target=lambda: first_result.append(limiter.run_with_retrieval_backend_budget_sync(first_work)),
        name="backend-budget-first",
    )
    second_thread = threading.Thread(
        target=lambda: second_result.append(
            limiter.run_with_retrieval_backend_budget_sync(lambda: second_started.set() or "second")
        ),
        name="backend-budget-second",
    )
    first_thread.start()
    assert first_started.wait(timeout=1) is True

    second_thread.start()
    time.sleep(0.05)
    assert second_started.is_set() is False

    release_first.set()
    first_thread.join(timeout=1)
    second_thread.join(timeout=1)

    assert first_result == ["first"]
    assert second_result == ["second"]
    assert second_started.is_set() is True


def test_retrieval_backend_budget_is_reentrant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.rag_runtime_limiter as limiter

    monkeypatch.setattr(limiter.settings, "RAG_VECTOR_SHARD_GLOBAL_MAX_CONCURRENCY", 1, raising=False)
    monkeypatch.setattr(limiter, "_backend_gate", None, raising=False)
    monkeypatch.setattr(limiter, "_backend_gate_limit", 0, raising=False)
    calls: list[str] = []

    def inner() -> str:
        calls.append("inner")
        return "inner"

    def outer() -> str:
        calls.append("outer")
        return limiter.run_with_retrieval_backend_budget_sync(inner)

    assert limiter.run_with_retrieval_backend_budget_sync(outer) == "inner"
    assert calls == ["outer", "inner"]
