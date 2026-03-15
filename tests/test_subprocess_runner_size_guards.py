import asyncio
import json
from pathlib import Path
from uuid import uuid4

import pytest

from app.core.config import settings
from app.parsing.subprocess_runner import SubprocessWorkerError, run_subprocess_worker


@pytest.mark.asyncio
async def test_run_subprocess_worker_payload_size_guard(monkeypatch):
    monkeypatch.setattr(settings, "SUBPROCESS_PAYLOAD_MAX_BYTES", 80, raising=False)

    tenant_id = uuid4()
    payload = {"action": "sleep", "tenant_id": str(tenant_id), "duration_sec": 0, "blob": "x" * 2000}

    with pytest.raises(SubprocessWorkerError) as exc:
        await run_subprocess_worker(tenant_id=tenant_id, payload=payload, timeout_sec=5)

    assert str(exc.value) == "payload_too_large"
    assert exc.value.details.get("max_bytes") == 80
    assert int(exc.value.details.get("actual_bytes") or 0) > 80


@pytest.mark.asyncio
async def test_run_subprocess_worker_result_size_guard(monkeypatch, tmp_path):
    import app.parsing.subprocess_runner as runner_mod

    monkeypatch.setattr(settings, "SUBPROCESS_RESULT_MAX_BYTES", 200, raising=False)
    monkeypatch.setattr(runner_mod, "_get_subprocess_workdir", lambda *, _tenant_id: tmp_path, raising=True)

    async def _fake_create_subprocess_exec(*args, **kwargs):  # noqa: ANN001, ANN002, ANN003
        # argv: python -m app.parsing.subprocess_worker <payload_path> <result_path>
        await asyncio.sleep(0)  # Sonar S7503
        result_path = Path(str(args[4]))
        oversized = {"ok": True, "data": {"blob": "x" * 5000}}
        result_path.write_text(json.dumps(oversized, ensure_ascii=False), encoding="utf-8")

        class _Proc:
            returncode = 0
            pid = 12345

            async def wait(self):  # noqa: ANN201
                await asyncio.sleep(0)  # Sonar S7503
                return 0

        return _Proc()

    monkeypatch.setattr(runner_mod.asyncio, "create_subprocess_exec", _fake_create_subprocess_exec, raising=True)

    tenant_id = uuid4()
    payload = {"action": "sleep", "tenant_id": str(tenant_id), "duration_sec": 0}
    with pytest.raises(SubprocessWorkerError) as exc:
        await run_subprocess_worker(tenant_id=tenant_id, payload=payload, timeout_sec=5, poll_interval_sec=0.01)

    assert str(exc.value) == "worker_result_too_large"
    assert exc.value.details.get("max_bytes") == 200
    assert int(exc.value.details.get("actual_bytes") or 0) > 200

