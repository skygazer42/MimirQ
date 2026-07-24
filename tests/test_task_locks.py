import pytest

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


def test_lock_values_are_unique_for_same_requester() -> None:
    values = {locks.make_lock_value("account-a") for _ in range(32)}

    assert len(values) == 32


@pytest.mark.asyncio
async def test_release_lock_keeps_replaced_lock() -> None:
    redis = FakeRedis()
    redis.store["lock:doc:1"] = "owner-b"
    redis.forbid_split_lock_ops = True

    await locks.release_lock(redis, key="lock:doc:1", value="owner-a")

    assert redis.store["lock:doc:1"] == "owner-b"
    assert redis.eval_calls == [(("lock:doc:1",), ("owner-a",))]


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
    assert redis.store[key] == "owner-a"
    assert redis.ttl[key] == 30
    assert redis.eval_calls == []


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
