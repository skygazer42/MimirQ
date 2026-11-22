import asyncio
import logging
import subprocess
import sys

import pytest


def test_worker_health_settings_do_not_import_torch() -> None:
    result = subprocess.run(
        [sys.executable, "-c", "import app.tasks.queue, sys; assert 'torch' not in sys.modules"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.asyncio
async def test_worker_warns_when_redis_heartbeat_fails(caplog, monkeypatch):  # noqa: ANN001
    from app.services.observability import task_queue
    from app.tasks.worker import WorkerSettings

    redis_client = object()
    heartbeat_attempted = asyncio.Event()

    async def failed_heartbeat(*, redis, **_kwargs):
        assert redis is redis_client
        heartbeat_attempted.set()
        raise OSError("simulated redis connect failure")

    monkeypatch.setattr(task_queue, "observe_task_worker_heartbeat", failed_heartbeat)
    caplog.set_level(logging.WARNING, logger="tasks.worker")
    context = {"redis": redis_client}
    try:
        await WorkerSettings.on_startup(context)
        await asyncio.wait_for(heartbeat_attempted.wait(), timeout=5)
        assert WorkerSettings.redis_settings.conn_retries >= 30
        assert "Worker heartbeat failed; retrying: simulated redis connect failure" in caplog.text
    finally:
        await WorkerSettings.on_shutdown(context)
