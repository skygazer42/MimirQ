import asyncio
import threading
from contextvars import ContextVar
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.rag.retrieval import orchestrator
from app.rag.runtime.streaming import executor as stream_executor
from app.rag.runtime.streaming.state import StreamOperation
from app.services.chat import enterprise_ontology as ontology


def test_document_retrieval_overlaps_ontology_and_joins_before_citations(monkeypatch):
    trace = ContextVar("ontology_test_trace", default="missing")
    trace.set("request-trace")
    documents_started = threading.Event()
    observed = []
    worker_db = SimpleNamespace(close=lambda: observed.append("closed"))

    def prepare(db, **scope):
        assert db is worker_db and trace.get() == "request-trace"
        assert documents_started.wait(2), "Document retrieval was blocked behind ontology planning"
        return ontology.OntologyEvidence(
            context={"fact": 0}, documents=[], metrics={"ontology_used": True}, action_proposal=None
        )

    class Session:
        def __enter__(self):
            return worker_db

        def __exit__(self, *_error):
            worker_db.close()

    def retrieve(runtime):
        documents_started.set()

    def citations(runtime):
        assert runtime.state["ontology_context"] == {"fact": 0}
        return runtime.state

    monkeypatch.setattr(orchestrator, "SessionLocal", Session, raising=False)
    monkeypatch.setattr(ontology, "prepare_ontology_evidence", prepare)
    monkeypatch.setattr(orchestrator, "_RETRIEVAL_RUNTIME_PHASES", (retrieve, citations))
    monkeypatch.setattr(orchestrator, "_run_retrieval_citations_hard_fallback_phase", citations)
    state = dict(
        question="核对金额及制度",
        ontology_enabled=True,
        db=object(),
        tenant_id=uuid4(),
        account_id="reader",
        dataset_id=uuid4(),
        document_ids=[],
        history=[],
    )

    assert orchestrator.run_retrieval(state)["metrics"]["ontology_used"] is True
    assert observed == ["closed"]


@pytest.mark.asyncio
async def test_stream_ontology_overlaps_retrieval_and_owns_its_session(monkeypatch):
    from app.rag.runtime.streaming import retrieval

    documents_started = threading.Event()
    observed = []
    worker_db = SimpleNamespace(close=lambda: observed.append("closed"))

    class Session:
        def __enter__(self):
            return worker_db

        def __exit__(self, *_error):
            worker_db.close()

    def prepare(db, **scope):
        assert db is worker_db
        assert documents_started.wait(2), "Stream retrieval waited for ontology instead of overlapping"
        return ontology.OntologyEvidence(
            context={"fact": 0}, documents=[], metrics={"ontology_used": True}, action_proposal=None
        )

    async def start(runtime):
        documents_started.set()

    async def join(runtime):
        await retrieval.collect_ontology_evidence(runtime)
        assert runtime.data.ontology_context == {"fact": 0}
        runtime.finished = True

    monkeypatch.setattr(retrieval, "SessionLocal", Session, raising=False)
    monkeypatch.setattr(ontology, "prepare_ontology_evidence", prepare)
    monkeypatch.setattr(
        stream_executor,
        "_STANDARD_OPERATIONS",
        (StreamOperation(start, streams=False), StreamOperation(join, streams=False)),
    )
    payload = dict(
        ontology_enabled=True,
        db=object(),
        tenant_id=uuid4(),
        account_id="reader",
        dataset_id=uuid4(),
        document_ids=[],
        question="核对金额及制度",
        history=[],
        conversation_id=None,
    )
    events = [
        event
        async for event in stream_executor.StandardStreamExecutor(
            engine=object(), inputs=stream_executor.StandardStreamInputs(payload)
        ).stream()
    ]

    assert events == [] and observed == ["closed"]


@pytest.mark.asyncio
async def test_stream_close_joins_the_ontology_worker_before_returning(monkeypatch):
    from app.rag.runtime.streaming import retrieval

    started = threading.Event()
    release = threading.Event()
    closed = threading.Event()

    class Session:
        def __enter__(self):
            return object()

        def __exit__(self, *_error):
            closed.set()

    def prepare(*_args, **_scope):
        started.set()
        assert release.wait(2)
        return None

    async def progress(runtime):
        await asyncio.to_thread(started.wait, 2)
        yield {"type": "event", "data": {"message": "检索中"}}

    monkeypatch.setattr(retrieval, "SessionLocal", Session, raising=False)
    monkeypatch.setattr(ontology, "prepare_ontology_evidence", prepare)
    monkeypatch.setattr(stream_executor, "_STANDARD_OPERATIONS", (StreamOperation(progress, streams=True),))
    payload = dict(
        ontology_enabled=True,
        db=object(),
        tenant_id=uuid4(),
        account_id="reader",
        dataset_id=uuid4(),
        document_ids=[],
        question="核对金额及制度",
        history=[],
        conversation_id=None,
    )
    stream = stream_executor.StandardStreamExecutor(
        engine=object(), inputs=stream_executor.StandardStreamInputs(payload)
    ).stream()
    await anext(stream)
    closing = asyncio.create_task(stream.aclose())
    await asyncio.sleep(0)
    assert not closed.is_set() and not closing.done()
    release.set()
    await asyncio.wait_for(closing, 2)
    assert closed.is_set()


@pytest.mark.asyncio
async def test_repeated_stream_cancellation_keeps_worker_owned_until_session_closes(monkeypatch):
    from app.rag.runtime.streaming import retrieval

    started, release, closed = (threading.Event() for _ in range(3))

    class Session:
        def __enter__(self):
            return object()

        def __exit__(self, *_error):
            closed.set()

    def prepare(*_args, **_scope):
        started.set()
        assert release.wait(2)
        return None

    async def waiting(runtime):
        await asyncio.Event().wait()

    monkeypatch.setattr(retrieval, "SessionLocal", Session)
    monkeypatch.setattr(ontology, "prepare_ontology_evidence", prepare)
    monkeypatch.setattr(stream_executor, "_STANDARD_OPERATIONS", (StreamOperation(waiting, streams=False),))
    payload = dict(
        ontology_enabled=True,
        tenant_id=uuid4(),
        account_id="reader",
        dataset_id=uuid4(),
        document_ids=[],
        question="核对金额及制度",
        history=[],
        conversation_id=None,
    )

    async def consume():
        return [
            event
            async for event in stream_executor.StandardStreamExecutor(
                engine=object(), inputs=stream_executor.StandardStreamInputs(payload)
            ).stream()
        ]

    consumer = asyncio.create_task(consume())
    assert await asyncio.to_thread(started.wait, 2)
    consumer.cancel()
    await asyncio.sleep(0)
    consumer.cancel()
    await asyncio.sleep(0)
    assert not consumer.done() and not closed.is_set()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await consumer
    assert closed.is_set()


@pytest.mark.asyncio
async def test_retrieval_failure_remains_primary_when_ontology_cleanup_also_fails(monkeypatch):
    from app.rag.runtime.streaming import retrieval

    started, release, closed = (threading.Event() for _ in range(3))
    primary = RuntimeError("document retrieval failed")

    class Session:
        def __enter__(self):
            return object()

        def __exit__(self, *_error):
            closed.set()

    def prepare(*_args, **_scope):
        started.set()
        assert release.wait(2)
        raise ValueError("ontology lookup failed")

    async def retrieve(runtime):
        assert await asyncio.to_thread(started.wait, 2)
        raise primary

    monkeypatch.setattr(retrieval, "SessionLocal", Session)
    monkeypatch.setattr(ontology, "prepare_ontology_evidence", prepare)
    monkeypatch.setattr(stream_executor, "_STANDARD_OPERATIONS", (StreamOperation(retrieve, streams=False),))
    payload = dict(
        ontology_enabled=True,
        tenant_id=uuid4(),
        account_id="reader",
        dataset_id=uuid4(),
        document_ids=[],
        question="核对金额及制度",
        history=[],
        conversation_id=None,
    )

    async def consume():
        return [
            event
            async for event in stream_executor.StandardStreamExecutor(
                engine=object(), inputs=stream_executor.StandardStreamInputs(payload)
            ).stream()
        ]

    consumer = asyncio.create_task(consume())
    assert await asyncio.to_thread(started.wait, 2)
    await asyncio.sleep(0)
    release.set()
    with pytest.raises(RuntimeError) as error:
        await consumer
    assert error.value is primary and closed.is_set()
    assert any("ValueError" in note for note in primary.__notes__)
