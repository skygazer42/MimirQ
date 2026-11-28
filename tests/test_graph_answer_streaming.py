import threading
from contextlib import aclosing

import pytest

from app.infrastructure.config import settings
from app.rag.runtime.graph import generation
from app.services.chat import stream_graph


@pytest.fixture
def stream_settings(monkeypatch):
    for name in (
        "RAG_CLAIM_CHECK_ENABLED",
        "RAG_VISIBLE_EVIDENCE_ONLY_ENABLED",
        "OUTPUT_GUARD_ENABLED",
        "RAG_CORRECTIVE_ENABLED",
        "RAG_FOLLOWUP_SUGGESTIONS_ENABLED",
        "SENTENCE_CITATIONS_INLINE_ENABLED",
    ):
        monkeypatch.setattr(settings, name, False)


@pytest.mark.asyncio
async def test_graph_sends_first_answer_chunk_before_generation_finishes(monkeypatch, stream_settings):
    release = threading.Event()
    closed = threading.Event()
    generation_finished = threading.Event()

    class Chain:
        def invoke(self, _inputs):
            generation_finished.set()
            return "first final"

        def stream(self, _inputs):
            try:
                yield "first "
                assert release.wait(2)
                generation_finished.set()
                yield "final"
            finally:
                closed.set()

    custom = []
    monkeypatch.setattr(generation, "get_stream_writer", lambda: custom.append, raising=False)

    def graph_events():
        yield "custom", {"event": "retrieval_start"}
        # The thread boundary stands in for LangGraph's custom-event queue.
        result = []

        def generate():
            result.append(
                generation._invoke_generation_chain(
                    chain=Chain(),
                    state={"question": "query", "format_instructions": "", "stream_answer": True},
                    ctx="evidence",
                    hist_text="",
                    pii_on=False,
                )[0]
            )

        worker = threading.Thread(target=generate)
        worker.start()
        try:
            for _ in range(1000):
                if custom:
                    break
                threading.Event().wait(0.001)
            assert custom, "Generation must publish a chunk before waiting for the complete answer"
            yield "custom", custom.pop(0)
            worker.join(2)
            while custom:
                yield "custom", custom.pop(0)
            yield "values", {"answer": result[0], "citations": [], "metrics": {}}
        finally:
            release.set()
            worker.join(2)

    state = stream_graph._GraphStreamAccumulator()
    async with aclosing(
        stream_graph._stream_graph_workflow_events(
            graph_events=graph_events,
            graph_cancel_event=threading.Event(),
            stream_state=state,
        )
    ) as events:
        first = await anext(events)
        assert first["type"] == "graph"
        chunk = await anext(events)
        assert chunk == {"type": "token", "data": {"content": "first "}}
        assert not generation_finished.is_set()
        release.set()
        rest = [event async for event in events]
    assert "".join(state.response_parts) == "first final"
    assert [event for event in rest if event["type"] == "token"] == [{"type": "token", "data": {"content": "final"}}]
    assert closed.is_set()


@pytest.mark.parametrize("guard", ["pii", "RAG_CLAIM_CHECK_ENABLED", "RAG_CORRECTIVE_ENABLED", "structured"])
def test_graph_keeps_complete_answer_checks_buffered(monkeypatch, stream_settings, guard):
    state = {"question": "query", "format_instructions": "", "stream_answer": True}
    if guard not in {"pii", "structured"}:
        monkeypatch.setattr(settings, guard, True)
    if guard == "structured":
        state["structured_output"] = True

    class Chain:
        def invoke(self, _inputs):
            return "validated answer"

        def stream(self, _inputs):
            pytest.fail("A response that may be rewritten must not expose unchecked chunks")

    answer, _ = generation._invoke_generation_chain(
        chain=Chain(),
        state=state,
        ctx="evidence",
        hist_text="",
        pii_on=guard == "pii",
    )
    assert answer == "validated answer"


@pytest.mark.asyncio
async def test_graph_streamed_text_must_match_final_persisted_answer():
    def graph_events():
        yield "custom", {"event": "answer_delta", "content": "wrong "}
        yield "values", {"answer": "correct answer"}

    with pytest.raises(RuntimeError, match="Streamed answer"):
        async with aclosing(
            stream_graph._stream_graph_workflow_events(
                graph_events=graph_events,
                graph_cancel_event=threading.Event(),
                stream_state=stream_graph._GraphStreamAccumulator(),
            )
        ) as events:
            _ = [event async for event in events]


@pytest.mark.asyncio
async def test_partial_graph_answer_never_appends_an_extractive_fallback(monkeypatch):
    from app.services.chat import stream_orchestrator

    async def broken(**_kwargs):
        yield {"type": "token", "data": {"content": "partial"}}
        raise ConnectionError("provider disconnected")

    async def fallback(**_kwargs):
        pytest.fail("A different fallback answer cannot follow already-emitted answer text")
        yield

    monkeypatch.setattr(stream_orchestrator, "stream_graph_chat_session_events", broken)
    monkeypatch.setattr(stream_orchestrator, "is_model_provider_unavailable_error", lambda _exc: True)
    monkeypatch.setattr(stream_orchestrator, "mark_model_provider_unavailable", lambda: None)
    events = [
        event
        async for event in stream_orchestrator._stream_graph_events(
            request_id="request",
            conversation_id=None,
            fallback_factory=fallback,
            stream_options=object(),
        )
    ]
    assert [event["type"] for event in events] == ["token", "error"]


def test_generation_failure_after_answer_text_is_not_retryable(monkeypatch, stream_settings):
    from app.rag.runtime.graph import tasks

    class Chain:
        def stream(self, _inputs):
            yield "partial"
            raise ConnectionError("provider disconnected")

    sent = []
    monkeypatch.setattr(generation, "get_stream_writer", lambda: sent.append)
    with pytest.raises(Exception) as failed:
        generation._invoke_generation_chain(
            chain=Chain(),
            state={"question": "query", "format_instructions": "", "stream_answer": True},
            ctx="evidence",
            hist_text="",
            pii_on=False,
        )
    assert len(sent) == 1
    assert not tasks._RAG_TASK_RETRY_POLICY.retry_on(failed.value)
