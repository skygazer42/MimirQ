import asyncio
from uuid import uuid4

import pytest

from app.core.config import settings
from app.parsing.subprocess_runner import SubprocessWorkerError, run_subprocess_worker


@pytest.mark.asyncio
async def test_run_subprocess_worker_log_size_guard(monkeypatch, tmp_path):
    import app.parsing.subprocess_runner as runner_mod

    monkeypatch.setattr(settings, "SUBPROCESS_LOG_MAX_BYTES", 50, raising=False)
    monkeypatch.setattr(runner_mod, "_get_subprocess_workdir", lambda *, _tenant_id: tmp_path, raising=True)

    async def _noop_terminate(_proc, *, grace_sec=2.0):  # noqa: ANN001, ANN201
        await asyncio.sleep(0)  # Sonar S7503
        return None

    monkeypatch.setattr(runner_mod, "_terminate_process_group", _noop_terminate, raising=True)

    async def _fake_create_subprocess_exec(*_args, **kwargs):  # noqa: ANN001, ANN002
        await asyncio.sleep(0)  # Sonar S7503
        stdout = kwargs.get("stdout")
        if stdout is not None:
            stdout.write(b"x" * 200)
            stdout.flush()

        class _Proc:
            returncode = None
            pid = 12345

        return _Proc()

    monkeypatch.setattr(runner_mod.asyncio, "create_subprocess_exec", _fake_create_subprocess_exec, raising=True)

    tenant_id = uuid4()
    payload = {"action": "sleep", "tenant_id": str(tenant_id), "duration_sec": 0}
    with pytest.raises(SubprocessWorkerError) as exc:
        await run_subprocess_worker(tenant_id=tenant_id, payload=payload, timeout_sec=5, poll_interval_sec=0.01)

    assert str(exc.value) == "worker_log_too_large"
    assert exc.value.details.get("max_bytes") == 50
    assert int(exc.value.details.get("actual_bytes") or 0) > 50

