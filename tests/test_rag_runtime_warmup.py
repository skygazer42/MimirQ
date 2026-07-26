import asyncio

import pytest

from app.services import rag_runtime_warmup as warmup


def _reset_state() -> None:
    warmup._set_rag_runtime_warmup_status(  # type: ignore[attr-defined]
        enabled=False,
        required_for_ready=False,
        ready=True,
        status="idle",
        attempted=0,
        completed=0,
        failed=0,
        elapsed_ms=None,
        embedding=warmup._new_probe_state("embedding"),  # type: ignore[attr-defined]
        reranker=warmup._new_probe_state("reranker"),  # type: ignore[attr-defined]
    )


@pytest.mark.asyncio
async def test_runtime_warmup_disabled_is_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_state()
    monkeypatch.setattr(warmup.settings, "RAG_RUNTIME_WARMUP_ENABLED", False, raising=False)
    monkeypatch.setattr(warmup.settings, "RAG_RUNTIME_WARMUP_REQUIRED_FOR_READY", False, raising=False)

    result = await warmup.warmup_rag_runtime()

    assert result["enabled"] is False
    assert result["status"] == "disabled"
    assert warmup.rag_runtime_warmup_ready() is True
    assert warmup.get_rag_runtime_warmup_status()["required_for_ready"] is False


@pytest.mark.asyncio
async def test_runtime_warmup_records_successful_embedding_and_reranker_probes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_state()
    monkeypatch.setattr(warmup.settings, "RAG_RUNTIME_WARMUP_ENABLED", True, raising=False)
    monkeypatch.setattr(warmup.settings, "RAG_RUNTIME_WARMUP_REQUIRED_FOR_READY", False, raising=False)

    async def _embedding_probe(timeout_sec: float) -> dict[str, object]:
        assert timeout_sec == 9.0
        return {
            "name": "embedding",
            "provider": "openai_compatible",
            "model": "text-embedding-3-small",
            "status": "completed",
            "ready": True,
            "elapsed_ms": 12.3,
        }

    async def _reranker_probe(timeout_sec: float) -> dict[str, object]:
        assert timeout_sec == 9.0
        return {
            "name": "reranker",
            "provider": "openai",
            "model": "bge-reranker",
            "status": "completed",
            "ready": True,
            "elapsed_ms": 23.4,
        }

    monkeypatch.setattr(warmup.settings, "RAG_RUNTIME_WARMUP_TIMEOUT_SEC", 9.0, raising=False)
    monkeypatch.setattr(warmup, "_probe_embedding_runtime", _embedding_probe, raising=True)
    monkeypatch.setattr(warmup, "_probe_reranker_runtime", _reranker_probe, raising=True)

    result = await warmup.warmup_rag_runtime()

    assert result["status"] == "completed"
    assert result["completed"] == 2
    assert result["failed"] == 0
    assert warmup.rag_runtime_warmup_ready() is True
    snapshot = warmup.get_rag_runtime_warmup_status()
    assert snapshot["embedding"]["status"] == "completed"
    assert snapshot["reranker"]["status"] == "completed"


@pytest.mark.asyncio
async def test_runtime_warmup_runs_embedding_and_reranker_probes_in_parallel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reset_state()
    monkeypatch.setattr(warmup.settings, "RAG_RUNTIME_WARMUP_ENABLED", True, raising=False)
    monkeypatch.setattr(warmup.settings, "RAG_RUNTIME_WARMUP_REQUIRED_FOR_READY", False, raising=False)
    monkeypatch.setattr(warmup.settings, "RAG_RUNTIME_WARMUP_TIMEOUT_SEC", 1.0, raising=False)

    both_started = asyncio.Event()
    started_count = 0

    async def _wait_for_peer() -> None:
        nonlocal started_count
        started_count += 1
        if started_count == 2:
            both_started.set()
        await asyncio.wait_for(both_started.wait(), timeout=0.5)

    async def _embedding_probe(_timeout_sec: float) -> dict[str, object]:
        await _wait_for_peer()
        return {"name": "embedding", "status": "completed", "ready": True, "elapsed_ms": 1.0}

    async def _reranker_probe(_timeout_sec: float) -> dict[str, object]:
        await _wait_for_peer()
        return {"name": "reranker", "status": "completed", "ready": True, "elapsed_ms": 1.0}

    monkeypatch.setattr(warmup, "_probe_embedding_runtime", _embedding_probe, raising=True)
    monkeypatch.setattr(warmup, "_probe_reranker_runtime", _reranker_probe, raising=True)

    result = await warmup.warmup_rag_runtime()

    assert result["status"] == "completed"
    assert started_count == 2


def test_embedding_probe_reuses_active_store_embedding_client(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Provider:
        def embed_query(self, _text: str) -> list[float]:
            return [0.1, 0.2]

    class _Store:
        def __init__(self, provider: _Provider) -> None:
            self._provider = provider

        def get_embedding_client(self) -> _Provider:
            return self._provider

    provider = _Provider()
    store = _Store(provider)

    monkeypatch.setattr("app.storage.vector.factory.get_vector_store", lambda: store)
    monkeypatch.setattr("app.storage.vector.factory.get_embedding_client", lambda: provider)

    result = warmup._probe_embedding_runtime_sync()  # type: ignore[attr-defined]

    assert result["status"] == "completed"
    assert result["dimension"] == 2


@pytest.mark.asyncio
async def test_runtime_warmup_scheduler_retains_task_until_completion(monkeypatch: pytest.MonkeyPatch) -> None:
    release = asyncio.Event()

    async def _delayed() -> dict[str, object]:
        await release.wait()
        return {"status": "completed"}

    monkeypatch.setattr(warmup.settings, "RAG_RUNTIME_WARMUP_ENABLED", True, raising=False)
    monkeypatch.setattr(warmup, "_delayed_warmup_rag_runtime", _delayed, raising=True)

    task = warmup.start_rag_runtime_warmup()

    assert isinstance(task, asyncio.Task)
    assert task in warmup._rag_runtime_warmup_tasks  # type: ignore[attr-defined]
    release.set()
    await task
    await asyncio.sleep(0)
    assert task not in warmup._rag_runtime_warmup_tasks  # type: ignore[attr-defined]


def test_runtime_warmup_scheduler_marks_runtime_error_as_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_state()
    closed = False

    class _ClosableCoro:
        def close(self) -> None:
            nonlocal closed
            closed = True

    monkeypatch.setattr(warmup.settings, "RAG_RUNTIME_WARMUP_ENABLED", True, raising=False)
    monkeypatch.setattr(warmup, "_delayed_warmup_rag_runtime", lambda: _ClosableCoro(), raising=True)

    def _raise_runtime_error(_coro: object) -> object:
        raise RuntimeError("no running event loop")

    task = warmup.start_rag_runtime_warmup(create_task=_raise_runtime_error)

    assert task is None
    assert closed is True
    assert not warmup._rag_runtime_warmup_tasks  # type: ignore[attr-defined]
    snapshot = warmup.get_rag_runtime_warmup_status()
    assert snapshot["status"] == "failed"
    assert snapshot["ready"] is False
    assert snapshot["attempted"] == 0
    assert snapshot["failed"] == 2
    assert snapshot["embedding"]["reason"] == "schedule_failed"
    assert snapshot["embedding"]["error"] == "no_running_event_loop"
    assert snapshot["reranker"]["reason"] == "schedule_failed"


def test_runtime_warmup_scheduler_marks_custom_schedule_error_as_failed(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_state()
    closed = False

    class _ClosableCoro:
        def close(self) -> None:
            nonlocal closed
            closed = True

    monkeypatch.setattr(warmup.settings, "RAG_RUNTIME_WARMUP_ENABLED", True, raising=False)
    monkeypatch.setattr(warmup, "_delayed_warmup_rag_runtime", lambda: _ClosableCoro(), raising=True)

    def _raise_value_error(_coro: object) -> object:
        raise ValueError("scheduler exploded")

    task = warmup.start_rag_runtime_warmup(create_task=_raise_value_error)

    assert task is None
    assert closed is True
    snapshot = warmup.get_rag_runtime_warmup_status()
    assert snapshot["status"] == "failed"
    assert snapshot["embedding"]["reason"] == "schedule_failed"
    assert snapshot["embedding"]["error"] == "scheduler exploded"
    assert snapshot["reranker"]["error"] == "scheduler exploded"


@pytest.mark.asyncio
async def test_runtime_warmup_fails_closed_when_required_probe_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    _reset_state()
    monkeypatch.setattr(warmup.settings, "RAG_RUNTIME_WARMUP_ENABLED", True, raising=False)
    monkeypatch.setattr(warmup.settings, "RAG_RUNTIME_WARMUP_REQUIRED_FOR_READY", True, raising=False)

    async def _embedding_probe(_timeout_sec: float) -> dict[str, object]:
        return {
            "name": "embedding",
            "provider": "openai_compatible",
            "model": "text-embedding-3-small",
            "status": "completed",
            "ready": True,
            "elapsed_ms": 8.0,
        }

    async def _reranker_probe(_timeout_sec: float) -> dict[str, object]:
        return {
            "name": "reranker",
            "provider": "openai",
            "model": "bge-reranker",
            "status": "failed",
            "ready": False,
            "elapsed_ms": 9.0,
            "error": "reranker timeout",
        }

    monkeypatch.setattr(warmup, "_probe_embedding_runtime", _embedding_probe, raising=True)
    monkeypatch.setattr(warmup, "_probe_reranker_runtime", _reranker_probe, raising=True)

    result = await warmup.warmup_rag_runtime()

    assert result["status"] == "failed"
    assert result["failed"] == 1
    assert warmup.rag_runtime_warmup_ready() is False
    assert warmup.get_rag_runtime_warmup_status()["reranker"]["error"] == "reranker timeout"
