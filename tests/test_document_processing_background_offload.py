import asyncio
import threading
import time

import pytest

from app.api.v1 import documents as documents_module


@pytest.fixture(autouse=True)
def _reset_background_processing_semaphores():  # noqa: ANN201
    documents_module._background_processing_semaphores.clear()
    yield
    documents_module._background_processing_semaphores.clear()


@pytest.mark.asyncio
async def test_document_processing_offloads_blocking_processor_off_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loop_thread_id = threading.get_ident()
    heartbeat_count = 0
    stop_heartbeat = asyncio.Event()
    observed_thread_ids: list[int] = []

    monkeypatch.setattr(documents_module.settings, "API_DOCUMENT_BACKGROUND_MAX_CONCURRENCY", 2, raising=False)

    async def _process(*_args, **_kwargs) -> str:  # noqa: ANN002, ANN003
        observed_thread_ids.append(threading.get_ident())
        time.sleep(0.15)
        return "ok"

    async def _heartbeat() -> None:
        nonlocal heartbeat_count
        while not stop_heartbeat.is_set():
            heartbeat_count += 1
            await asyncio.sleep(0.01)

    monkeypatch.setattr(documents_module.document_processor, "process_document", _process, raising=True)

    heartbeat_task = asyncio.create_task(_heartbeat())
    try:
        result = await documents_module.run_document_processing_limited("doc-1")
    finally:
        stop_heartbeat.set()
        await heartbeat_task

    assert result == "ok"
    assert observed_thread_ids
    assert observed_thread_ids[0] != loop_thread_id
    assert heartbeat_count >= 5


@pytest.mark.asyncio
async def test_document_processing_offload_respects_background_concurrency_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_started = threading.Event()
    release_first = threading.Event()
    events: list[tuple[str, str]] = []

    monkeypatch.setattr(documents_module.settings, "API_DOCUMENT_BACKGROUND_MAX_CONCURRENCY", 1, raising=False)

    async def _process(label: str, *_args, **_kwargs) -> str:  # noqa: ANN002, ANN003
        events.append(("start", label))
        if label == "first":
            first_started.set()
            assert release_first.wait(timeout=3.0)
        else:
            assert release_first.is_set()
        time.sleep(0.05)
        events.append(("end", label))
        return label

    monkeypatch.setattr(documents_module.document_processor, "process_document", _process, raising=True)

    first_task = asyncio.create_task(documents_module.run_document_processing_limited("first"))
    assert await asyncio.to_thread(first_started.wait, 3.0)

    second_task = asyncio.create_task(documents_module.run_document_processing_limited("second"))
    await asyncio.sleep(0.05)
    assert events == [("start", "first")]

    release_first.set()
    results = await asyncio.gather(first_task, second_task)

    assert results == ["first", "second"]
    assert events == [
        ("start", "first"),
        ("end", "first"),
        ("start", "second"),
        ("end", "second"),
    ]


@pytest.mark.asyncio
async def test_document_processing_offload_holds_semaphore_until_cancelled_worker_finishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_started = threading.Event()
    second_started = threading.Event()
    release_first = threading.Event()
    events: list[tuple[str, str]] = []

    monkeypatch.setattr(documents_module.settings, "API_DOCUMENT_BACKGROUND_MAX_CONCURRENCY", 1, raising=False)

    async def _process(label: str, *_args, **_kwargs) -> str:  # noqa: ANN002, ANN003
        events.append(("start", label))
        if label == "first":
            first_started.set()
            assert release_first.wait(timeout=3.0)
        else:
            second_started.set()
        time.sleep(0.05)
        events.append(("end", label))
        return label

    monkeypatch.setattr(documents_module.document_processor, "process_document", _process, raising=True)

    first_task = asyncio.create_task(documents_module.run_document_processing_limited("first"))
    assert await asyncio.to_thread(first_started.wait, 3.0)

    second_task = asyncio.create_task(documents_module.run_document_processing_limited("second"))
    await asyncio.sleep(0.05)
    assert events == [("start", "first")]

    first_task.cancel()
    await asyncio.sleep(0.05)
    assert not second_started.is_set()
    assert events == [("start", "first")]

    release_first.set()

    with pytest.raises(asyncio.CancelledError):
        await first_task
    assert await asyncio.to_thread(second_started.wait, 3.0)
    assert await second_task == "second"
    assert events == [
        ("start", "first"),
        ("end", "first"),
        ("start", "second"),
        ("end", "second"),
    ]


@pytest.mark.asyncio
async def test_document_processing_offload_preserves_cancellation_when_worker_fails(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    first_started = threading.Event()
    second_started = threading.Event()
    release_first = threading.Event()
    events: list[tuple[str, str]] = []

    monkeypatch.setattr(documents_module.settings, "API_DOCUMENT_BACKGROUND_MAX_CONCURRENCY", 1, raising=False)

    async def _process(label: str, *_args, **_kwargs) -> str:  # noqa: ANN002, ANN003
        events.append(("start", label))
        if label == "first":
            first_started.set()
            assert release_first.wait(timeout=3.0)
            raise RuntimeError("worker failed after cancellation")
        second_started.set()
        time.sleep(0.05)
        events.append(("end", label))
        return label

    monkeypatch.setattr(documents_module.document_processor, "process_document", _process, raising=True)

    first_task = asyncio.create_task(documents_module.run_document_processing_limited("first"))
    assert await asyncio.to_thread(first_started.wait, 3.0)

    second_task = asyncio.create_task(documents_module.run_document_processing_limited("second"))
    await asyncio.sleep(0.05)
    assert events == [("start", "first")]

    first_task.cancel()
    first_task.cancel()
    await asyncio.sleep(0.05)
    assert not second_started.is_set()
    assert events == [("start", "first")]

    with caplog.at_level("WARNING", logger=documents_module.logger.name):
        release_first.set()
        with pytest.raises(asyncio.CancelledError):
            await first_task

    assert await asyncio.to_thread(second_started.wait, 3.0)
    assert await second_task == "second"
    assert events == [
        ("start", "first"),
        ("start", "second"),
        ("end", "second"),
    ]
    assert "failed after request cancellation" in caplog.text
