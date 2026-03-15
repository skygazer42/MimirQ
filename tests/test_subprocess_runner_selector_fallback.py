import json
from pathlib import Path
from uuid import uuid4

import pytest

from app.parsing.subprocess_runner import run_subprocess_worker
from tests.helpers.async_utils import yield_control


@pytest.mark.asyncio
async def test_run_subprocess_worker_falls_back_when_asyncio_subprocess_unavailable(monkeypatch, tmp_path):
    import app.parsing.subprocess_runner as runner_mod

    monkeypatch.setattr(runner_mod, "_get_subprocess_workdir", lambda *, _tenant_id: tmp_path, raising=True)

    async def _fake_create_subprocess_exec(*_args, **_kwargs):  # noqa: ANN001, ANN002
        await yield_control()
        raise NotImplementedError

    monkeypatch.setattr(runner_mod.asyncio, "create_subprocess_exec", _fake_create_subprocess_exec, raising=True)

    def _fake_popen(args, **_kwargs):  # noqa: ANN001
        result_path = Path(args[-1])
        result_path.write_text(
            json.dumps({"ok": True, "data": {"slept_sec": 0.0}}, ensure_ascii=False),
            encoding="utf-8",
        )

        class _Proc:
            pid = 12345
            returncode = None

            def poll(self):  # noqa: ANN201
                self.returncode = 0
                return 0

            def terminate(self):  # noqa: ANN201
                self.returncode = -15

            def kill(self):  # noqa: ANN201
                self.returncode = -9

            def wait(self, *_args, **_kwargs):  # noqa: ANN001, ANN002, ANN201
                self.returncode = 0
                return 0

        return _Proc()

    monkeypatch.setattr(runner_mod.subprocess, "Popen", _fake_popen, raising=True)

    tenant_id = uuid4()
    payload = {"action": "sleep", "tenant_id": str(tenant_id), "duration_sec": 0.0}
    result = await run_subprocess_worker(
        tenant_id=tenant_id,
        payload=payload,
        timeout_sec=5,
        poll_interval_sec=0.01,
    )

    assert result.get("slept_sec") == pytest.approx(0.0)
