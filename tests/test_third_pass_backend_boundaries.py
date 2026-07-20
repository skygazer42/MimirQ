import asyncio
import multiprocessing
import time
from pathlib import Path
from uuid import uuid4

import pytest
import yaml


@pytest.mark.skipif("fork" not in multiprocessing.get_all_start_methods(), reason="requires fork semantics")
def test_concurrent_glossary_candidate_writes_do_not_lose_updates(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.rag.industry_rules.loaders import yaml_loader

    worker_count = 4
    root = tmp_path / "rulesets"
    ruleset = root / "test"
    ruleset.mkdir(parents=True)
    (ruleset / "glossary.yaml").write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(yaml_loader, "_ruleset_root", lambda: root)

    context = multiprocessing.get_context("fork")
    writers_waiting = context.Value("i", 0)
    original_write_text = Path.write_text

    def _synchronized_write(path: Path, data: str, *args, **kwargs) -> int:
        if path.name == "glossary.generated.yaml":
            with writers_waiting.get_lock():
                writers_waiting.value += 1
            deadline = time.monotonic() + 5
            while writers_waiting.value < worker_count and time.monotonic() < deadline:
                time.sleep(0.01)
        return original_write_text(path, data, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", _synchronized_write)

    def _write_candidate(token: str) -> None:
        yaml_loader.write_glossary_candidates("test", [{"token": token}])

    tokens = {f"term-{index}" for index in range(worker_count)}
    processes = [context.Process(target=_write_candidate, args=(token,)) for token in tokens]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=10)
        assert process.exitcode == 0

    generated = yaml.safe_load((ruleset / "glossary.generated.yaml").read_text(encoding="utf-8"))
    assert set(generated) == tokens


@pytest.mark.asyncio
async def test_subprocess_is_terminated_when_cancelled_during_poll_sleep(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    from app.parsing import subprocess_runner

    class _RunningProcess:
        pid = 123
        returncode = None

    process = _RunningProcess()
    terminated = False

    async def _spawn(*_args, **_kwargs):
        return process

    async def _cancel_on_sleep(_delay: float) -> None:
        raise asyncio.CancelledError

    async def _terminate(target, **_kwargs) -> None:
        nonlocal terminated
        assert target is process
        terminated = True
        target.returncode = -15

    monkeypatch.setattr(subprocess_runner, "_get_subprocess_workdir", lambda **_kwargs: tmp_path)
    monkeypatch.setattr(subprocess_runner.asyncio, "create_subprocess_exec", _spawn)
    monkeypatch.setattr(subprocess_runner.asyncio, "sleep", _cancel_on_sleep)
    monkeypatch.setattr(subprocess_runner, "_terminate_process_group", _terminate)

    with pytest.raises(asyncio.CancelledError):
        await subprocess_runner.run_subprocess_worker(
            tenant_id=uuid4(),
            payload={"document_id": "test"},
        )

    assert terminated is True
