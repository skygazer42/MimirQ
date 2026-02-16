from __future__ import annotations

from uuid import uuid4

import pytest

from app.parsing.subprocess_runner import SubprocessWorkerError


def test_classify_subprocess_timeout_error() -> None:
    from app.parsing.errors import ParsingTimeoutError, classify_parser_subprocess_error

    classified = classify_parser_subprocess_error(SubprocessWorkerError("worker_timeout"))
    assert isinstance(classified, ParsingTimeoutError)


def test_classify_subprocess_unsupported_error() -> None:
    from app.parsing.errors import ParsingUnsupportedError, classify_parser_subprocess_error

    classified = classify_parser_subprocess_error(SubprocessWorkerError("Unsupported file type: .zip"))
    assert isinstance(classified, ParsingUnsupportedError)


def test_classify_subprocess_internal_error() -> None:
    from app.parsing.errors import ParsingInternalError, classify_parser_subprocess_error

    classified = classify_parser_subprocess_error(SubprocessWorkerError("boom", details={"type": "RuntimeError"}))
    assert isinstance(classified, ParsingInternalError)


@pytest.mark.asyncio
async def test_run_parser_subprocess_retries_internal_errors(monkeypatch):  # noqa: ANN001
    import app.parsing.subprocess_runner as runner_mod
    from app.parsing.errors import ParsingInternalError

    calls = {"count": 0}

    async def _fake_run_subprocess_worker(*, tenant_id, payload, **kwargs):  # noqa: ANN001, ANN202
        calls["count"] += 1
        if calls["count"] == 1:
            raise SubprocessWorkerError("boom", details={"type": "RuntimeError"})
        return {"ok": True}

    async def _fake_sleep(_sec):  # noqa: ANN001, ANN202
        return None

    monkeypatch.setattr(runner_mod, "run_subprocess_worker", _fake_run_subprocess_worker, raising=True)
    monkeypatch.setattr(runner_mod.asyncio, "sleep", _fake_sleep, raising=True)

    tenant_id = uuid4()
    result = await runner_mod.run_parser_subprocess(
        tenant_id=tenant_id,
        payload={"action": "sleep", "tenant_id": str(tenant_id), "duration_sec": 0},
        max_attempts=2,
        base_delay_sec=0.01,
    )

    assert result == {"ok": True}
    assert calls["count"] == 2

    # Exhausted retries should raise a typed error.
    calls["count"] = 0

    async def _always_fail(*, tenant_id, payload, **kwargs):  # noqa: ANN001, ANN202
        calls["count"] += 1
        raise SubprocessWorkerError("boom", details={"type": "RuntimeError"})

    monkeypatch.setattr(runner_mod, "run_subprocess_worker", _always_fail, raising=True)
    with pytest.raises(ParsingInternalError):
        await runner_mod.run_parser_subprocess(
            tenant_id=tenant_id,
            payload={"action": "sleep", "tenant_id": str(tenant_id), "duration_sec": 0},
            max_attempts=2,
            base_delay_sec=0.01,
        )
    assert calls["count"] == 2


@pytest.mark.asyncio
async def test_run_parser_subprocess_does_not_retry_unsupported(monkeypatch):  # noqa: ANN001
    import app.parsing.subprocess_runner as runner_mod
    from app.parsing.errors import ParsingUnsupportedError

    calls = {"count": 0}

    async def _fail_unsupported(*, tenant_id, payload, **kwargs):  # noqa: ANN001, ANN202
        calls["count"] += 1
        raise SubprocessWorkerError("Unsupported file type: .zip", details={"type": "ValueError"})

    async def _sleep_should_not_be_called(_sec):  # noqa: ANN001, ANN202
        raise AssertionError("should not sleep for unsupported errors")

    monkeypatch.setattr(runner_mod, "run_subprocess_worker", _fail_unsupported, raising=True)
    monkeypatch.setattr(runner_mod.asyncio, "sleep", _sleep_should_not_be_called, raising=True)

    tenant_id = uuid4()
    with pytest.raises(ParsingUnsupportedError):
        await runner_mod.run_parser_subprocess(
            tenant_id=tenant_id,
            payload={"action": "sleep", "tenant_id": str(tenant_id), "duration_sec": 0},
            max_attempts=3,
            base_delay_sec=0.01,
        )

    assert calls["count"] == 1

