from __future__ import annotations

import re
import time

import pytest
from prometheus_client import generate_latest


class _FakeRedis:
    def __init__(self) -> None:
        self._sorted_sets: dict[str, dict[str, float]] = {}
        self._expires: dict[str, int] = {}

    async def ping(self):  # noqa: ANN001, ANN202
        return True

    async def zadd(self, key, mapping):  # noqa: ANN001, ANN202
        k = str(key)
        z = self._sorted_sets.setdefault(k, {})
        for member, score in (mapping or {}).items():
            z[str(member)] = float(score)
        return True

    async def expire(self, key, seconds):  # noqa: ANN001, ANN202
        self._expires[str(key)] = int(seconds or 0)
        return True

    async def zcard(self, key):  # noqa: ANN001, ANN202
        return len(self._sorted_sets.get(str(key), {}))

    async def zremrangebyscore(self, key, min_score, max_score):  # noqa: ANN001, ANN202
        k = str(key)
        z = self._sorted_sets.get(k, {})
        if not z:
            return 0

        mn = float("-inf") if str(min_score) in {"-inf", "(-inf"} else float(min_score)
        mx = float(max_score)
        to_delete = [m for m, s in z.items() if mn <= float(s) <= mx]
        for m in to_delete:
            z.pop(m, None)
        return len(to_delete)


@pytest.mark.asyncio
async def test_refresh_snapshot_reports_depth_and_active_workers(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services.task_queue_observability_service as svc
    from app.core.config import settings

    fake = _FakeRedis()
    queue_name = "mimirq"

    # Queue depth: 2 enqueued jobs.
    await fake.zadd(queue_name, {"job-a": 1.0, "job-b": 2.0})

    # Worker registry: 2 active + 1 stale.
    reg = f"ops:task_queue:workers:{queue_name}"
    now = time.time()
    await fake.zadd(reg, {"w1": now, "w2": now, "stale": now - 3600.0})

    monkeypatch.setattr(settings, "TASK_QUEUE_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "TASK_WORKER_HEARTBEAT_TTL_SEC", 30, raising=False)

    async def _fake_get_arq_redis():  # noqa: ANN202
        return fake

    monkeypatch.setattr(svc, "_get_arq_redis", _fake_get_arq_redis, raising=True)

    snap = await svc.refresh_task_queue_observability_snapshot(source="test")
    assert snap.enabled is True
    assert snap.queue_name == queue_name
    assert snap.broker_up is True
    assert snap.queue_depth == 2
    assert snap.workers_active == 2
    assert snap.error is None


@pytest.mark.asyncio
async def test_refresh_updates_prometheus_gauges_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services.task_queue_observability_service as svc
    from app.core.config import settings

    fake = _FakeRedis()
    queue_name = "mimirq"
    await fake.zadd(queue_name, {"job-a": 1.0, "job-b": 2.0})

    monkeypatch.setattr(settings, "PROMETHEUS_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "TASK_QUEUE_ENABLED", True, raising=False)

    async def _fake_get_arq_redis():  # noqa: ANN202
        return fake

    monkeypatch.setattr(svc, "_get_arq_redis", _fake_get_arq_redis, raising=True)

    await svc.refresh_task_queue_observability_snapshot(source="test")

    text = generate_latest().decode("utf-8", errors="replace")
    assert re.search(r'task_queue_broker_up\{queue="mimirq"\} 1(\.0)?\b', text)
    assert re.search(r'task_queue_depth\{queue="mimirq"\} 2(\.0)?\b', text)


@pytest.mark.asyncio
async def test_poller_start_stop_is_best_effort(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.services.task_queue_observability_service as svc
    from app.core.config import settings

    # Avoid any broker dependency for this test.
    monkeypatch.setattr(settings, "PROMETHEUS_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "TASK_QUEUE_ENABLED", False, raising=False)

    svc.start_task_queue_observability_poller()
    await svc.stop_task_queue_observability_poller()
