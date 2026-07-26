import asyncio
import threading
import time

import pytest

from app.services import document_lifecycle_service
from app.tasks import jobs as jobs_module


@pytest.mark.asyncio
async def test_document_processing_helper_offloads_async_processor_off_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    caller_thread_id = threading.get_ident()
    observed_thread_ids: list[int] = []
    heartbeat_count = 0
    stop_heartbeat = asyncio.Event()

    async def _process(*_args, **_kwargs) -> str:  # noqa: ANN002, ANN003
        observed_thread_ids.append(threading.get_ident())
        time.sleep(0.15)
        return "ok"

    async def _heartbeat() -> None:
        nonlocal heartbeat_count
        while not stop_heartbeat.is_set():
            heartbeat_count += 1
            await asyncio.sleep(0.01)

    monkeypatch.setattr(jobs_module.document_processor, "process_document", _process, raising=True)

    heartbeat_task = asyncio.create_task(_heartbeat())
    try:
        result = await jobs_module._run_document_processing_without_blocking_event_loop("doc-1")
    finally:
        stop_heartbeat.set()
        await heartbeat_task

    assert result == "ok"
    assert observed_thread_ids
    assert observed_thread_ids == [observed_thread_ids[0]]
    assert observed_thread_ids[0] != caller_thread_id
    assert heartbeat_count >= 5


@pytest.mark.asyncio
async def test_document_processing_helper_waits_for_worker_completion_before_raising_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker_started = threading.Event()
    release_worker = threading.Event()
    worker_finished = threading.Event()

    async def _process(*_args, **_kwargs) -> str:  # noqa: ANN002, ANN003
        worker_started.set()
        assert release_worker.wait(timeout=3.0)
        worker_finished.set()
        return "ok"

    monkeypatch.setattr(jobs_module.document_processor, "process_document", _process, raising=True)

    task = asyncio.create_task(
        jobs_module._run_document_processing_without_blocking_event_loop("doc-1")
    )
    assert await asyncio.to_thread(worker_started.wait, 1.0)

    task.cancel()
    await asyncio.sleep(0.05)

    assert task.done() is False
    assert worker_finished.is_set() is False

    release_worker.set()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert worker_finished.is_set() is True


@pytest.mark.asyncio
async def test_delete_step_helper_offloads_blocking_step_off_event_loop() -> None:
    caller_thread_id = threading.get_ident()
    observed_thread_ids: list[int] = []
    heartbeat_count = 0
    stop_heartbeat = asyncio.Event()

    def _delete_step(label: str) -> str:
        observed_thread_ids.append(threading.get_ident())
        time.sleep(0.15)
        return label

    async def _heartbeat() -> None:
        nonlocal heartbeat_count
        while not stop_heartbeat.is_set():
            heartbeat_count += 1
            await asyncio.sleep(0.01)

    heartbeat_task = asyncio.create_task(_heartbeat())
    try:
        result = await document_lifecycle_service._run_delete_step_without_blocking_event_loop(
            _delete_step,
            "deleted",
        )
    finally:
        stop_heartbeat.set()
        await heartbeat_task

    assert result == "deleted"
    assert observed_thread_ids
    assert observed_thread_ids == [observed_thread_ids[0]]
    assert observed_thread_ids[0] != caller_thread_id
    assert heartbeat_count >= 5


@pytest.mark.asyncio
async def test_delete_step_helper_waits_for_worker_completion_before_raising_cancellation() -> None:
    worker_started = threading.Event()
    release_worker = threading.Event()
    worker_finished = threading.Event()

    def _delete_step() -> str:
        worker_started.set()
        assert release_worker.wait(timeout=3.0)
        worker_finished.set()
        return "deleted"

    task = asyncio.create_task(
        document_lifecycle_service._run_delete_step_without_blocking_event_loop(_delete_step)
    )
    assert await asyncio.to_thread(worker_started.wait, 1.0)

    task.cancel()
    await asyncio.sleep(0.05)

    assert task.done() is False
    assert worker_finished.is_set() is False

    release_worker.set()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert worker_finished.is_set() is True


@pytest.mark.asyncio
async def test_delete_session_is_created_used_and_closed_on_the_same_worker_thread() -> None:
    caller_thread_id = threading.get_ident()
    events: list[tuple[str, int]] = []

    class _Session:
        def close(self) -> None:
            events.append(("close", threading.get_ident()))

    def _session_factory() -> _Session:
        events.append(("create", threading.get_ident()))
        return _Session()

    def _step(*, db: _Session) -> str:
        assert isinstance(db, _Session)
        events.append(("use", threading.get_ident()))
        return "deleted"

    result = await document_lifecycle_service._run_delete_step_without_blocking_event_loop(
        document_lifecycle_service._run_document_delete_session_step,
        _session_factory,
        _step,
        {},
    )

    assert result == "deleted"
    assert [name for name, _thread_id in events] == ["create", "use", "close"]
    worker_thread_ids = {thread_id for _name, thread_id in events}
    assert len(worker_thread_ids) == 1
    assert caller_thread_id not in worker_thread_ids
