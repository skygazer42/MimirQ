import asyncio
import threading
from types import SimpleNamespace
from uuid import uuid4

import pytest


@pytest.mark.parametrize(
    ("mode", "with_context"),
    [("invoke", False), ("invoke", True), ("stream", False), ("stream", True)],
)
def test_real_functional_workflow_keeps_session_out_of_graph_state(
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    with_context: bool,
) -> None:
    import app.rag.pipelines.langgraph as graph
    import app.rag.retrieval.orchestrator as orchestrator

    caller_thread_id = threading.get_ident()
    cancel_event = threading.Event()
    events: list[tuple[str, int]] = []
    admitted_cancel_events: list[threading.Event | None] = []

    class WorkerDB:
        def __init__(self) -> None:
            events.append(("create", threading.get_ident()))

        def rollback(self) -> None:
            events.append(("rollback", threading.get_ident()))

        def close(self) -> None:
            events.append(("close", threading.get_ident()))

    def fake_retrieval(state):  # noqa: ANN001, ANN202
        assert isinstance(state["db"], WorkerDB)
        events.append(("retrieve", threading.get_ident()))
        return {**state, "docs": [], "citations": [], "metrics": {}}

    def fake_generation(state):  # noqa: ANN001, ANN202
        assert "db" not in state
        return {**state, "answer": "ok"}

    def fake_admission(func, *args, cancel_event=None, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
        admitted_cancel_events.append(cancel_event)
        return func(*args, **kwargs)

    monkeypatch.setattr(graph, "SessionLocal", WorkerDB, raising=False)
    monkeypatch.setattr(orchestrator, "run_retrieval", fake_retrieval)
    monkeypatch.setattr(graph, "_generate_node", fake_generation)
    monkeypatch.setattr(graph, "run_blocking_retrieval_call_sync", fake_admission)
    monkeypatch.setattr(graph.settings, "RAG_CORRECTIVE_ENABLED", False)
    monkeypatch.setattr(graph.settings, "STREAM_WRITER_ENABLED", False)

    assert graph.rag_workflow.get_context_jsonschema()["type"] == "object"
    state = {"question": f"session-boundary-{uuid4()}", "history": [], "metrics": {}}
    config = {"configurable": {"thread_id": f"graph-session-{uuid4()}"}}
    context = {"cancel_event": cancel_event} if with_context else None
    if mode == "invoke":
        result = graph.rag_workflow.invoke(state, config=config, context=context)
    else:
        result = list(graph.rag_workflow.stream(state, config=config, context=context, stream_mode="values"))[-1]

    assert result["answer"] == "ok"
    assert "db" not in result
    assert "db" not in graph.rag_workflow.get_state(config).values
    assert admitted_cancel_events == ([None] if context is None else [cancel_event])
    assert [name for name, _thread_id in events] == ["create", "retrieve", "rollback", "close"]
    assert len({thread_id for _name, thread_id in events}) == 1
    assert events[0][1] != caller_thread_id


@pytest.mark.asyncio
async def test_retrieval_admission_is_process_wide_across_event_loops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.rag_runtime_limiter as limiter

    first_started = threading.Event()
    release_first = threading.Event()
    second_started = threading.Event()
    first_errors: list[BaseException] = []
    monkeypatch.setattr(limiter.settings, "RAG_RETRIEVAL_OFFLOAD_MAX_CONCURRENCY", 1)

    def first_work() -> None:
        first_started.set()
        assert release_first.wait(timeout=2)

    def run_first_loop() -> None:
        try:
            asyncio.run(limiter.run_blocking_retrieval_call(first_work))
        except BaseException as exc:  # noqa: BLE001
            first_errors.append(exc)

    first_thread = threading.Thread(target=run_first_loop)
    first_thread.start()
    assert await asyncio.to_thread(first_started.wait, 1)

    second_task = asyncio.create_task(
        limiter.run_blocking_retrieval_call(second_started.set)
    )
    await asyncio.sleep(0.05)
    second_was_blocked = not second_started.is_set()
    release_first.set()
    await second_task
    first_thread.join(timeout=2)

    assert second_was_blocked is True
    assert first_thread.is_alive() is False
    assert first_errors == []


@pytest.mark.asyncio
async def test_sync_graph_retrieval_shares_async_admission_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.rag_runtime_limiter as limiter

    first_started = threading.Event()
    release_first = threading.Event()
    graph_retrieval_started = threading.Event()
    monkeypatch.setattr(limiter.settings, "RAG_RETRIEVAL_OFFLOAD_MAX_CONCURRENCY", 1)

    def first_work() -> None:
        first_started.set()
        assert release_first.wait(timeout=2)

    first_task = asyncio.create_task(limiter.run_blocking_retrieval_call(first_work))
    assert await asyncio.to_thread(first_started.wait, 1)

    graph_task = asyncio.create_task(
        asyncio.to_thread(
            limiter.run_blocking_retrieval_call_sync,
            graph_retrieval_started.set,
        )
    )
    await asyncio.sleep(0.05)
    graph_was_blocked = not graph_retrieval_started.is_set()
    release_first.set()
    await asyncio.gather(first_task, graph_task)

    assert graph_was_blocked is True


@pytest.mark.asyncio
async def test_sync_graph_retrieval_drops_cancelled_queued_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.rag_runtime_limiter as limiter

    first_started = threading.Event()
    release_first = threading.Event()
    cancel_graph = threading.Event()
    graph_retrieval_ran = threading.Event()
    monkeypatch.setattr(limiter.settings, "RAG_RETRIEVAL_OFFLOAD_MAX_CONCURRENCY", 1)

    def first_work() -> None:
        first_started.set()
        assert release_first.wait(timeout=2)

    first_task = asyncio.create_task(limiter.run_blocking_retrieval_call(first_work))
    assert await asyncio.to_thread(first_started.wait, 1)
    graph_task = asyncio.create_task(
        asyncio.to_thread(
            limiter.run_blocking_retrieval_call_sync,
            graph_retrieval_ran.set,
            cancel_event=cancel_graph,
        )
    )
    await asyncio.sleep(0.05)
    cancel_graph.set()
    with pytest.raises(limiter.RetrievalAdmissionCancelledError):
        await graph_task

    release_first.set()
    await first_task
    assert graph_retrieval_ran.is_set() is False


@pytest.mark.asyncio
async def test_generic_managed_worker_does_not_hold_retrieval_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.services.rag_runtime_limiter as limiter

    graph_started = threading.Event()
    release_graph = threading.Event()
    retrieval_started = threading.Event()
    monkeypatch.setattr(limiter.settings, "RAG_RETRIEVAL_OFFLOAD_MAX_CONCURRENCY", 1)
    monkeypatch.setattr(
        limiter,
        "SessionLocal",
        lambda: SimpleNamespace(close=lambda: None),
    )

    def graph_work(_db):  # noqa: ANN001, ANN202
        graph_started.set()
        assert release_graph.wait(timeout=2)

    graph_task = asyncio.create_task(
        limiter.run_blocking_call_with_managed_session(
            graph_work,
            request_db=SimpleNamespace(rollback=lambda: None),
        )
    )
    assert await asyncio.to_thread(graph_started.wait, 1)
    retrieval_task = asyncio.create_task(
        limiter.run_blocking_retrieval_call(retrieval_started.set)
    )
    assert await asyncio.to_thread(retrieval_started.wait, 1)

    release_graph.set()
    await asyncio.gather(graph_task, retrieval_task)


def test_graph_retrieval_uses_shared_gate_and_owns_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.pipelines.langgraph as graph
    import app.rag.retrieval.orchestrator as orchestrator

    events: list[str] = []

    class WorkerDB:
        def __init__(self) -> None:
            events.append("create")

        def rollback(self) -> None:
            events.append("rollback")

        def close(self) -> None:
            events.append("close")

    def fake_retrieval(state):  # noqa: ANN001, ANN202
        assert isinstance(state["db"], WorkerDB)
        events.append("retrieve")
        return {"db": state["db"], "metrics": {}}

    def fake_admission(func, *args, cancel_event=None, **kwargs):  # noqa: ANN001, ANN002, ANN003, ANN202
        assert cancel_event is None
        events.append("gate")
        return func(*args, **kwargs)

    monkeypatch.setattr(graph, "SessionLocal", WorkerDB)
    monkeypatch.setattr(orchestrator, "run_retrieval", fake_retrieval)
    monkeypatch.setattr(graph, "run_blocking_retrieval_call_sync", fake_admission, raising=False)

    assert graph._retrieve_node({"question": "test"}) == {"metrics": {}}
    assert events == ["gate", "create", "retrieve", "rollback", "close"]
