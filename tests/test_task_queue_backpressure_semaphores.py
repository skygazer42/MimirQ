from __future__ import annotations

import pytest

from tests.helpers.async_utils import yield_control


class _RetryError(Exception):
    def __init__(self, *, defer: int):  # noqa: ANN001
        super().__init__(f"retry defer={defer}")
        self.defer = int(defer)


class _FakeRedis:
    def __init__(self) -> None:
        self._counters: dict[str, int] = {}
        self._expires: dict[str, int] = {}

    async def incr(self, key):  # noqa: ANN001, ANN202
        await yield_control()
        k = str(key)
        self._counters[k] = int(self._counters.get(k, 0)) + 1
        return self._counters[k]

    async def decr(self, key):  # noqa: ANN001, ANN202
        await yield_control()
        k = str(key)
        self._counters[k] = int(self._counters.get(k, 0)) - 1
        return self._counters[k]

    async def expire(self, key, ttl_sec):  # noqa: ANN001, ANN202
        await yield_control()
        self._expires[str(key)] = int(ttl_sec or 0)
        return True

    async def delete(self, key):  # noqa: ANN001, ANN202
        await yield_control()
        self._counters.pop(str(key), None)
        return True


@pytest.mark.asyncio
async def test_tenant_semaphore_enforces_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.tasks.locks as locks

    monkeypatch.setattr(locks, "get_retry_exc", lambda: _RetryError, raising=True)

    redis = _FakeRedis()
    key = await locks.tenant_acquire(redis, tenant_id="t1", kind="doc", limit=1, ttl_sec=10, retry_defer_sec=3)
    assert key == "sem:tenant:t1:doc"

    with pytest.raises(_RetryError) as excinfo:
        await locks.tenant_acquire(redis, tenant_id="t1", kind="doc", limit=1, ttl_sec=10, retry_defer_sec=3)
    assert excinfo.value.defer == 3
    assert redis._counters["sem:tenant:t1:doc"] == 1

    await locks.tenant_release(redis, key)
    assert "sem:tenant:t1:doc" not in redis._counters


@pytest.mark.asyncio
async def test_dataset_semaphore_enforces_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.tasks.locks as locks

    monkeypatch.setattr(locks, "get_retry_exc", lambda: _RetryError, raising=True)

    redis = _FakeRedis()
    key = await locks.dataset_acquire(
        redis,
        tenant_id="t1",
        dataset_id="d1",
        kind="doc",
        limit=1,
        ttl_sec=10,
        retry_defer_sec=2,
    )
    assert key == "sem:dataset:t1:d1:doc"

    with pytest.raises(_RetryError) as excinfo:
        await locks.dataset_acquire(
            redis,
            tenant_id="t1",
            dataset_id="d1",
            kind="doc",
            limit=1,
            ttl_sec=10,
            retry_defer_sec=2,
        )
    assert excinfo.value.defer == 2
    assert redis._counters["sem:dataset:t1:d1:doc"] == 1

    await locks.dataset_release(redis, key)
    assert "sem:dataset:t1:d1:doc" not in redis._counters


@pytest.mark.asyncio
async def test_dataset_semaphore_skips_when_dataset_id_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.tasks.locks as locks

    monkeypatch.setattr(locks, "get_retry_exc", lambda: _RetryError, raising=True)

    redis = _FakeRedis()
    key = await locks.dataset_acquire(redis, tenant_id="t1", dataset_id="", kind="doc", limit=1)
    assert key is None
    assert redis._counters == {}
