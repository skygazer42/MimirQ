
import asyncio
from collections.abc import AsyncIterator, Callable

import pytest
from langchain_core.documents import Document


class _StreamingChain:
    def __init__(self, *, tokens: list[str], captured_inputs: list[dict[str, object]]) -> None:
        self._tokens = tokens
        self._captured_inputs = captured_inputs

    def __or__(self, _other: object) -> "_StreamingChain":
        return self

    async def astream(self, inputs: dict[str, object]) -> AsyncIterator[str]:
        self._captured_inputs.append(dict(inputs))
        for token in self._tokens:
            yield token


class _StreamingPrompt:
    def __init__(self, *, tokens: list[str], captured_inputs: list[dict[str, object]]) -> None:
        self._tokens = tokens
        self._captured_inputs = captured_inputs

    def __or__(self, _other: object) -> _StreamingChain:
        return _StreamingChain(tokens=self._tokens, captured_inputs=self._captured_inputs)


class _FakeLLM:
    model_name = "fake-llm"

    def bind(self, **_kwargs: object) -> "_FakeLLM":
        return self


class _FakeEngine:
    def __init__(self, *, tokens: list[str]) -> None:
        self.models: dict[str, object] = {}
        self._captured_inputs: list[dict[str, object]] = []
        self.prompt_template = _StreamingPrompt(tokens=tokens, captured_inputs=self._captured_inputs)

    def _doc_key(self, doc: Document) -> str:
        return str(getattr(doc, "id", None) or doc.metadata.get("chunk_id") or doc.page_content)

    def _score_question_complexity(self, _question: str, _history: list[dict[str, object]]) -> float:
        return 300.0

    def _select_llm(self, _question: str, _history: list[dict[str, object]]) -> tuple[object, str, str]:
        return _FakeLLM(), "fast", "test-route"


class _SuccessfulToolResult:
    def __init__(self) -> None:
        self.success = True
        self.data = {"success": True, "expression": "2+2", "result": 4}
        self.error = None
        self.metadata = {"backend": "test-tool"}


class _SuccessfulToolRegistry:
    def __init__(self, calls: list[tuple[str, dict[str, object]]]) -> None:
        self._calls = calls

    async def call_tool(self, name: str, arguments: dict[str, object]) -> _SuccessfulToolResult:
        self._calls.append((name, arguments))
        return _SuccessfulToolResult()


async def _collect_events(stream: AsyncIterator[dict[str, object]]) -> list[dict[str, object]]:
    return [event async for event in stream]


def _build_doc(chunk_id: str, text: str) -> Document:
    return Document(
        page_content=text,
        id=chunk_id,
        metadata={
            "chunk_id": chunk_id,
            "document_id": f"doc-{chunk_id}",
            "source": f"{chunk_id}.txt",
            "score": 0.8,
            "relevance_score": 0.8,
        },
    )


def _configure_review_stream(
    monkeypatch: pytest.MonkeyPatch,
    rag_agent: object,
    runner: object,
    *,
    critic_review: Callable[..., dict[str, object]],
) -> None:
    async def fake_plan(**_kwargs: object) -> list[object]:
        return [rag_agent.AgenticPlanStep(query="review query", rationale="review plan")]

    async def fake_offload(work: Callable[[object], object], *, request_db: object) -> object:
        return work(object())

    monkeypatch.setattr(runner, "_plan", fake_plan)
    monkeypatch.setattr(rag_agent, "build_rag_state", lambda **kwargs: dict(kwargs))
    monkeypatch.setattr(
        rag_agent,
        "run_retrieval",
        lambda _state: {
            "docs": [_build_doc("review", "review evidence")],
            "citations": [],
            "metrics": {"retrieval_mode": "hybrid", "top_relevance_score": 1.0},
            "abstain_triggered": False,
            "abstain_reason": None,
        },
    )
    monkeypatch.setattr(rag_agent, "run_blocking_retrieval_call_with_managed_session", fake_offload)
    monkeypatch.setattr(rag_agent, "build_citations_from_docs", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(rag_agent, "_build_history_text", lambda _history: "")
    monkeypatch.setattr(rag_agent, "_build_context", lambda _docs, **_kwargs: "review evidence")
    monkeypatch.setattr(
        rag_agent,
        "run_self_rag_reflection",
        lambda **_kwargs: {"verdict": "supported", "need_retrieval": False},
    )
    monkeypatch.setattr(rag_agent, "run_critic_review", critic_review)
    monkeypatch.setattr(rag_agent.settings, "RAG_MULTI_AGENT_ENABLED", False, raising=False)
    monkeypatch.setattr(rag_agent.settings, "RAG_AGENTIC_TOOLS_ENABLED", False, raising=False)
    monkeypatch.setattr(rag_agent.settings, "RAG_CRAG_STREAMING_ENABLED", False, raising=False)
    monkeypatch.setattr(rag_agent.settings, "RAG_SELF_RAG_ENABLED", True, raising=False)
    monkeypatch.setattr(rag_agent.settings, "RAG_CRITIC_ENABLED", True, raising=False)
    monkeypatch.setattr(rag_agent.settings, "RAG_AGENTIC_MAX_RETRIEVE_ROUNDS", 1, raising=False)


@pytest.mark.asyncio
async def test_stream_yields_answering_before_generation_prep_and_aclose_skips_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.agents.rag_agent as rag_agent

    engine = _FakeEngine(tokens=["unused"])
    runner = rag_agent.AgenticRAGRunner(engine)
    context_calls: list[list[Document]] = []

    def fake_build_context(docs: list[Document], **_kwargs: object) -> str:
        context_calls.append(docs)
        return "review evidence"

    _configure_review_stream(
        monkeypatch,
        rag_agent,
        runner,
        critic_review=lambda **_kwargs: {"verdict": "pass", "citation_missing": False},
    )
    monkeypatch.setattr(rag_agent, "_build_context", fake_build_context)
    stream = runner.stream(request=rag_agent.AgenticStreamRequest(question="Answer incrementally", db=object()))

    while True:
        event = await anext(stream)
        if event == {"type": "agentic_step", "data": {"step": "answering"}}:
            break

    assert context_calls == []
    assert engine._captured_inputs == []

    await stream.aclose()

    assert context_calls == []
    assert engine._captured_inputs == []
    with pytest.raises(StopAsyncIteration):
        await anext(stream)


@pytest.mark.asyncio
async def test_stream_reuses_history_mutated_by_retrieval_and_prepares_history_before_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.agents.rag_agent as rag_agent

    engine = _FakeEngine(tokens=["answer"])
    runner = rag_agent.AgenticRAGRunner(engine)
    base_history: list[dict[str, object]] | None = None
    generation_histories: list[list[dict[str, object]]] = []
    preparation_order: list[str] = []

    def fake_build_rag_state(**kwargs: object) -> dict[str, object]:
        nonlocal base_history
        base_history = kwargs["history"]
        return dict(kwargs)

    def fake_retrieval(state: dict[str, object]) -> dict[str, object]:
        history = state["history"]
        assert history is base_history
        history.append({"role": "assistant", "content": "added during retrieval"})
        return {
            "docs": [_build_doc("history", "history evidence")],
            "citations": [],
            "metrics": {"retrieval_mode": "hybrid", "top_relevance_score": 1.0},
            "abstain_triggered": False,
            "abstain_reason": None,
        }

    def fake_build_history_text(history: list[dict[str, object]]) -> str:
        preparation_order.append("history")
        generation_histories.append(history)
        return "|".join(str(item["content"]) for item in history)

    def fake_build_context(_docs: list[Document], **_kwargs: object) -> str:
        preparation_order.append("context")
        return "history evidence"

    _configure_review_stream(
        monkeypatch,
        rag_agent,
        runner,
        critic_review=lambda **_kwargs: {"verdict": "pass", "citation_missing": False},
    )
    monkeypatch.setattr(rag_agent, "build_rag_state", fake_build_rag_state)
    monkeypatch.setattr(rag_agent, "run_retrieval", fake_retrieval)
    monkeypatch.setattr(rag_agent, "_build_history_text", fake_build_history_text)
    monkeypatch.setattr(rag_agent, "_build_context", fake_build_context)

    await _collect_events(
        runner.stream(
            request=rag_agent.AgenticStreamRequest(
                question="Use shared history",
                history=[{"role": "user", "content": "original"}],
                db=object(),
            )
        )
    )

    assert generation_histories == [base_history]
    assert generation_histories[0] is base_history
    assert preparation_order == ["history", "context"]
    assert engine._captured_inputs[0]["history"] == "original|added during retrieval"


@pytest.mark.asyncio
async def test_stream_yields_self_reflect_before_critic_completes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.agents.rag_agent as rag_agent

    runner = rag_agent.AgenticRAGRunner(_FakeEngine(tokens=["answer"]))
    self_reflect_received = asyncio.Event()
    critic_release = asyncio.Event()
    critic_completed = asyncio.get_running_loop().create_future()

    def fake_critic_review(**_kwargs: object) -> dict[str, object]:
        critic_completed.set_result(None)
        return {"verdict": "pass", "citation_missing": False}

    _configure_review_stream(
        monkeypatch,
        rag_agent,
        runner,
        critic_review=fake_critic_review,
    )
    stream = runner.stream(request=rag_agent.AgenticStreamRequest(question="Review incrementally", db=object()))

    async def consume_through_critic() -> tuple[dict[str, object], dict[str, object]]:
        while True:
            event = await anext(stream)
            if event["type"] == "agentic_step" and event["data"].get("step") == "self_reflect":
                self_reflect_received.set()
                await critic_release.wait()
                return event, await stream.__anext__()

    consumer = asyncio.create_task(consume_through_critic())
    await asyncio.wait_for(self_reflect_received.wait(), timeout=5)

    assert not critic_completed.done()

    critic_release.set()
    self_reflect_event, critic_event = await consumer

    assert self_reflect_event["data"] == {
        "step": "self_reflect",
        "verdict": "supported",
        "need_retrieval": False,
    }
    assert critic_completed.done()
    assert critic_event == {
        "type": "agentic_step",
        "data": {"step": "critic_review", "verdict": "pass", "citation_missing": False},
    }
    await stream.aclose()


@pytest.mark.asyncio
async def test_stream_aclose_after_self_reflect_skips_critic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.agents.rag_agent as rag_agent

    runner = rag_agent.AgenticRAGRunner(_FakeEngine(tokens=["answer"]))
    critic_calls: list[dict[str, object]] = []

    def fake_critic_review(**kwargs: object) -> dict[str, object]:
        critic_calls.append(dict(kwargs))
        return {"verdict": "pass", "citation_missing": False}

    _configure_review_stream(
        monkeypatch,
        rag_agent,
        runner,
        critic_review=fake_critic_review,
    )
    stream = runner.stream(request=rag_agent.AgenticStreamRequest(question="Stop after reflection", db=object()))

    while True:
        event = await anext(stream)
        if event["type"] == "agentic_step" and event["data"].get("step") == "self_reflect":
            break

    await stream.aclose()

    assert critic_calls == []
    with pytest.raises(StopAsyncIteration):
        await anext(stream)


@pytest.mark.asyncio
async def test_stream_hands_off_to_multi_agent_runner_without_local_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.agents.rag_agent as rag_agent

    engine = _FakeEngine(tokens=["unused"])
    runner = rag_agent.AgenticRAGRunner(engine)

    async def fake_plan(**_kwargs: object) -> list[object]:
        return [
            rag_agent.AgenticPlanStep(query="one", rationale="test"),
            rag_agent.AgenticPlanStep(query="two", rationale="test"),
        ]

    forwarded_events = [
        {"type": "agentic_step", "data": {"step": "delegated"}},
        {"type": "done", "data": {"route": "multi-agent"}},
    ]
    forwarded_requests: list[object] = []

    class _MultiAgentRunner:
        async def stream(self, *, request: object) -> AsyncIterator[dict[str, object]]:
            forwarded_requests.append(request)
            for event in forwarded_events:
                yield event

    monkeypatch.setattr(runner, "_plan", fake_plan)
    monkeypatch.setattr(rag_agent.settings, "RAG_MULTI_AGENT_ENABLED", True, raising=False)
    monkeypatch.setattr(rag_agent, "get_multi_agent_runner", lambda *, engine: _MultiAgentRunner())

    request = rag_agent.AgenticStreamRequest(question="delegate?")
    events = await _collect_events(runner.stream(request=request))

    assert events == forwarded_events
    assert forwarded_requests == [request]


@pytest.mark.asyncio
async def test_stream_offloads_rounds_and_preserves_generation_reflection_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.agents.rag_agent as rag_agent

    engine = _FakeEngine(tokens=['{"answer":', '"ok"}'])
    runner = rag_agent.AgenticRAGRunner(engine)
    request_db = object()
    worker_dbs = [object(), object()]
    offload_calls: list[object] = []
    retrieval_questions: list[str] = []
    self_rag_calls: list[dict[str, object]] = []
    critic_calls: list[dict[str, object]] = []

    async def fake_plan(**_kwargs: object) -> list[object]:
        return [
            rag_agent.AgenticPlanStep(query="first question", rationale="plan-1"),
            rag_agent.AgenticPlanStep(query="second question", rationale="plan-2"),
        ]

    async def fake_offload(work: Callable[[object], object], *, request_db: object) -> object:
        offload_calls.append(request_db)
        return work(worker_dbs[len(offload_calls) - 1])

    first_doc = _build_doc("chunk-1", "alpha evidence")
    second_doc = _build_doc("chunk-2", "beta evidence")

    def fake_retrieval(state: dict[str, object]) -> dict[str, object]:
        retrieval_questions.append(str(state["question"]))
        assert state["db"] is worker_dbs[len(retrieval_questions) - 1]
        if len(retrieval_questions) == 1:
            return {
                "docs": [first_doc],
                "citations": [],
                "metrics": {"retrieval_mode": "hybrid", "top_relevance_score": 0.0},
                "abstain_triggered": False,
                "abstain_reason": None,
            }
        return {
            "docs": [second_doc],
            "citations": [{"id": "final-citation"}],
            "metrics": {"retrieval_mode": "hybrid", "top_relevance_score": 0.0},
            "abstain_triggered": False,
            "abstain_reason": None,
        }

    def fake_self_rag_reflection(**kwargs: object) -> dict[str, object]:
        self_rag_calls.append(dict(kwargs))
        return {"verdict": "supported", "need_retrieval": False}

    def fake_critic_review(**kwargs: object) -> dict[str, object]:
        critic_calls.append(dict(kwargs))
        return {
            "verdict": "pass",
            "citation_missing": False,
            "supported_claims": 2,
            "total_claims": 2,
            "style_issues": ["none"],
            "reason_codes": ["ok"],
        }

    monkeypatch.setattr(runner, "_plan", fake_plan)
    monkeypatch.setattr(rag_agent, "build_rag_state", lambda **kwargs: dict(kwargs))
    monkeypatch.setattr(
        rag_agent,
        "build_chained_query",
        lambda query, findings: query if not findings else f"{query} :: {findings[-1]}",
    )
    monkeypatch.setattr(rag_agent, "summarize_chain_step", lambda citations: f"summary-{len(citations)}")
    monkeypatch.setattr(rag_agent, "run_retrieval", fake_retrieval)
    monkeypatch.setattr(rag_agent, "run_blocking_retrieval_call_with_managed_session", fake_offload)
    monkeypatch.setattr(
        rag_agent,
        "build_citations_from_docs",
        lambda docs, **_kwargs: [{"doc_ids": [doc.metadata["document_id"] for doc in docs]}],
    )
    monkeypatch.setattr(rag_agent, "_build_history_text", lambda history: f"history:{len(history)}")
    monkeypatch.setattr(
        rag_agent,
        "_build_context",
        lambda docs, **_kwargs: (
            "|".join(str(doc.page_content) for doc in docs) or "No relevant reference materials found."
        ),
    )
    monkeypatch.setattr(rag_agent, "run_self_rag_reflection", fake_self_rag_reflection)
    monkeypatch.setattr(rag_agent, "run_critic_review", fake_critic_review)
    monkeypatch.setattr(rag_agent.settings, "RAG_MULTI_AGENT_ENABLED", False, raising=False)
    monkeypatch.setattr(rag_agent.settings, "RAG_AGENTIC_TOOLS_ENABLED", False, raising=False)
    monkeypatch.setattr(rag_agent.settings, "RAG_CRAG_STREAMING_ENABLED", False, raising=False)
    monkeypatch.setattr(rag_agent.settings, "RAG_SELF_RAG_ENABLED", True, raising=False)
    monkeypatch.setattr(rag_agent.settings, "RAG_CRITIC_ENABLED", True, raising=False)
    monkeypatch.setattr(rag_agent.settings, "RAG_AGENTIC_MAX_RETRIEVE_ROUNDS", 2, raising=False)
    monkeypatch.setattr(rag_agent.settings, "RAG_AGENTIC_REFLECT_TOP_CITATIONS_MIN", 2, raising=False)
    monkeypatch.setattr(rag_agent.settings, "RAG_AGENTIC_REFLECT_TOP_SCORE_MIN", 0.95, raising=False)

    events = await _collect_events(
        runner.stream(
            request=rag_agent.AgenticStreamRequest(
                question="What happened?",
                history=[{"role": "user", "content": "earlier"}],
                db=request_db,
                structured_output=True,
            )
        )
    )

    assert offload_calls == [request_db, request_db]
    assert retrieval_questions == ["first question", "second question :: summary-0"]
    assert [
        (
            event["type"],
            event["data"].get("step") if isinstance(event.get("data"), dict) else None,
        )
        for event in events
        if event["type"] in {"route", "agentic_step", "citations", "token", "done"}
    ] == [
        ("route", None),
        ("agentic_step", "planning"),
        ("agentic_step", "retrieving"),
        ("agentic_step", "retrieving"),
        ("citations", None),
        ("agentic_step", "answering"),
        ("token", None),
        ("token", None),
        ("agentic_step", "self_reflect"),
        ("agentic_step", "critic_review"),
        ("done", None),
    ]
    assert events[2]["data"] == {
        "step": "retrieving",
        "round": 1,
        "query": "first question",
        "rationale": "plan-1",
    }
    assert events[3]["data"] == {
        "step": "retrieving",
        "round": 2,
        "query": "second question :: summary-0",
        "rationale": "plan-2",
    }
    assert events[4] == {"type": "citations", "data": [{"doc_ids": ["doc-chunk-1", "doc-chunk-2"]}]}
    assert "".join(event["data"]["content"] for event in events if event["type"] == "token") == '{"answer":"ok"}'
    assert events[-1]["data"]["structured"] is True
    assert events[-1]["data"]["structured_data"] == {"answer": "ok"}
    assert events[-1]["data"]["metrics"]["agentic_rounds"] == 2
    assert events[-1]["data"]["metrics"]["docs_returned"] == 2
    assert events[-1]["data"]["metrics"]["agentic_self_rag_used"] is True
    assert events[-1]["data"]["metrics"]["agentic_critic_used"] is True
    assert engine._captured_inputs == [
        {
            "context": "alpha evidence|beta evidence",
            "history": "history:1",
            "question": "What happened?",
            "format_instructions": "",
        }
    ]
    assert self_rag_calls[0]["citations"] == [{"doc_ids": ["doc-chunk-1", "doc-chunk-2"]}]
    assert critic_calls[0]["evidence_text"] == "alpha evidence\nbeta evidence"


@pytest.mark.asyncio
async def test_stream_yields_abstain_token_before_counting_and_aclose_skips_metrics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.agents.rag_agent as rag_agent

    runner = rag_agent.AgenticRAGRunner(_FakeEngine(tokens=["unused"]))
    token_counter_calls: list[str] = []

    _configure_review_stream(
        monkeypatch,
        rag_agent,
        runner,
        critic_review=lambda **_kwargs: {"verdict": "pass", "citation_missing": False},
    )
    monkeypatch.setattr(
        rag_agent,
        "run_retrieval",
        lambda _state: {
            "docs": [],
            "citations": [],
            "metrics": {"retrieval_mode": "hybrid"},
            "abstain_triggered": True,
            "abstain_reason": "no_evidence",
        },
    )
    monkeypatch.setattr(
        rag_agent,
        "num_tokens_from_string",
        lambda value: token_counter_calls.append(value) or 7,
    )
    monkeypatch.setattr(rag_agent.settings, "RAG_SELF_RAG_ENABLED", False, raising=False)
    monkeypatch.setattr(rag_agent.settings, "RAG_CRITIC_ENABLED", False, raising=False)
    stream = runner.stream(request=rag_agent.AgenticStreamRequest(question="No evidence", db=object()))

    while True:
        event = await anext(stream)
        if event["type"] == "token":
            break

    assert event == {
        "type": "token",
        "data": {"content": rag_agent._UNABLE_TO_ANSWER_MESSAGE},
    }
    assert token_counter_calls == []

    await stream.aclose()

    assert token_counter_calls == []
    with pytest.raises(StopAsyncIteration):
        await anext(stream)


@pytest.mark.asyncio
async def test_tool_phase_yields_call_before_execution_then_populates_result_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.agents.rag_agent as rag_agent

    runner = rag_agent.AgenticRAGRunner(_FakeEngine(tokens=["unused"]))
    state = rag_agent._AgenticRetrievalState()
    tool_calls: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(
        runner,
        "_plan_tool_invocations",
        lambda **_kwargs: [
            rag_agent.AgenticToolInvocation(
                name="calculate",
                arguments={"expression": "2+2"},
                rationale="calculate exactly",
            )
        ],
    )
    monkeypatch.setattr(
        rag_agent,
        "get_agentic_tool_registry",
        lambda: _SuccessfulToolRegistry(tool_calls),
    )
    phase = runner._stream_tool_phase(
        question="2+2?",
        document_ids=None,
        dataset_id=None,
        account_id=None,
        state=state,
    )

    tool_call_event = await anext(phase)

    assert tool_call_event == {
        "type": "agentic_step",
        "data": {"step": "tool_call", "tool": "calculate", "rationale": "calculate exactly"},
    }
    assert tool_calls == []
    assert state.tool_metrics == []
    assert state.tool_context_blocks == []

    tool_result_event = await phase.__anext__()

    assert tool_calls == [("calculate", {"expression": "2+2"})]
    assert tool_result_event == {
        "type": "agentic_step",
        "data": {"step": "tool_result", "tool": "calculate", "success": True, "error": None},
    }
    assert state.tool_metrics == [{"name": "calculate", "success": True, "backend": "test-tool", "error": None}]
    assert state.tool_context_blocks == ["[Tool: calculate]\nExpression: 2+2\nResult: 4"]
    with pytest.raises(StopAsyncIteration):
        await anext(phase)


@pytest.mark.asyncio
async def test_tool_phase_aclose_after_call_skips_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.agents.rag_agent as rag_agent

    runner = rag_agent.AgenticRAGRunner(_FakeEngine(tokens=["unused"]))
    state = rag_agent._AgenticRetrievalState()
    tool_calls: list[tuple[str, dict[str, object]]] = []
    monkeypatch.setattr(
        runner,
        "_plan_tool_invocations",
        lambda **_kwargs: [rag_agent.AgenticToolInvocation(name="calculate", arguments={"expression": "2+2"})],
    )
    monkeypatch.setattr(
        rag_agent,
        "get_agentic_tool_registry",
        lambda: _SuccessfulToolRegistry(tool_calls),
    )
    phase = runner._stream_tool_phase(
        question="2+2?",
        document_ids=None,
        dataset_id=None,
        account_id=None,
        state=state,
    )

    tool_call_event = await anext(phase)
    assert tool_call_event["data"]["step"] == "tool_call"

    await phase.aclose()

    assert tool_calls == []
    assert state.tool_metrics == []
    assert state.tool_context_blocks == []
    with pytest.raises(StopAsyncIteration):
        await anext(phase)


@pytest.mark.asyncio
async def test_stream_records_tool_registry_failure_and_abstains_without_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.agents.rag_agent as rag_agent

    engine = _FakeEngine(tokens=["unused"])
    runner = rag_agent.AgenticRAGRunner(engine)
    request_db = object()
    offload_calls: list[object] = []

    async def fake_plan(**_kwargs: object) -> list[object]:
        return [rag_agent.AgenticPlanStep(query="lookup", rationale="plan")]

    async def fake_offload(work: Callable[[object], object], *, request_db: object) -> object:
        offload_calls.append(request_db)
        return work(object())

    monkeypatch.setattr(runner, "_plan", fake_plan)
    monkeypatch.setattr(
        runner,
        "_plan_tool_invocations",
        lambda **_kwargs: [rag_agent.AgenticToolInvocation(name="calculate", arguments={"expression": "2+2"})],
    )
    monkeypatch.setattr(rag_agent, "build_rag_state", lambda **kwargs: dict(kwargs))
    monkeypatch.setattr(
        rag_agent,
        "run_retrieval",
        lambda _state: {
            "docs": [],
            "citations": [],
            "metrics": {"retrieval_mode": "hybrid"},
            "abstain_triggered": True,
            "abstain_reason": "no_evidence",
        },
    )
    monkeypatch.setattr(rag_agent, "run_blocking_retrieval_call_with_managed_session", fake_offload)
    monkeypatch.setattr(rag_agent, "get_agentic_tool_registry", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(rag_agent, "build_citations_from_docs", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(rag_agent.settings, "RAG_MULTI_AGENT_ENABLED", False, raising=False)
    monkeypatch.setattr(rag_agent.settings, "RAG_AGENTIC_TOOLS_ENABLED", True, raising=False)
    monkeypatch.setattr(rag_agent.settings, "RAG_CRAG_STREAMING_ENABLED", False, raising=False)
    monkeypatch.setattr(rag_agent.settings, "RAG_SELF_RAG_ENABLED", False, raising=False)
    monkeypatch.setattr(rag_agent.settings, "RAG_CRITIC_ENABLED", False, raising=False)

    events = await _collect_events(
        runner.stream(
            request=rag_agent.AgenticStreamRequest(
                question="2 + 2?",
                db=request_db,
            )
        )
    )

    assert offload_calls == [request_db]
    assert [event["type"] for event in events] == [
        "route",
        "agentic_step",
        "agentic_step",
        "citations",
        "token",
        "done",
    ]
    assert events[2]["data"]["step"] == "retrieving"
    assert events[4]["data"]["content"] == rag_agent._UNABLE_TO_ANSWER_MESSAGE
    assert events[-1]["data"]["metrics"]["agentic_tool_calls"] == [
        {"name": "registry_init", "success": False, "backend": None, "error": "tool_registry_failed"}
    ]
    assert events[-1]["data"]["metrics"]["abstain_reason"] == "no_evidence"


@pytest.mark.asyncio
async def test_crag_web_search_yields_before_context_incorporation_and_aclose_skips_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.agents.rag_agent as rag_agent

    runner = rag_agent.AgenticRAGRunner(_FakeEngine(tokens=["unused"]))
    retrieval_state = rag_agent._AgenticRetrievalState()

    async def fake_offload(work: Callable[[object], object], *, request_db: object) -> object:
        return work(object())

    async def fake_crag_streaming(**_kwargs: object) -> dict[str, object]:
        return {
            "used": True,
            "provider": "web",
            "web_result_count": 2,
            "context_block": "[deferred-crag-context]",
        }

    monkeypatch.setattr(
        rag_agent,
        "run_retrieval",
        lambda _state: {
            "docs": [],
            "citations": [],
            "metrics": {"retrieval_mode": "hybrid", "top_relevance_score": 0.0},
            "abstain_triggered": False,
            "abstain_reason": None,
        },
    )
    monkeypatch.setattr(rag_agent, "run_blocking_retrieval_call_with_managed_session", fake_offload)
    monkeypatch.setattr(rag_agent, "run_crag_streaming", fake_crag_streaming)
    monkeypatch.setattr(rag_agent.settings, "RAG_CRAG_STREAMING_ENABLED", True, raising=False)
    monkeypatch.setattr(rag_agent.settings, "RAG_AGENTIC_REFLECT_TOP_CITATIONS_MIN", 2, raising=False)
    monkeypatch.setattr(rag_agent.settings, "RAG_AGENTIC_REFLECT_TOP_SCORE_MIN", 0.95, raising=False)
    phase = runner._stream_retrieval_phase(
        question="Need CRAG",
        plan_steps=[rag_agent.AgenticPlanStep(query="primary", rationale="plan")],
        max_rounds=1,
        base_state={"retrieval_mode": "hybrid"},
        request_db=object(),
        state=retrieval_state,
    )

    retrieving_event = await anext(phase)
    web_search_event = await phase.__anext__()

    assert retrieving_event["data"]["step"] == "retrieving"
    assert web_search_event == {
        "type": "agentic_step",
        "data": {"step": "web_search", "provider": "web", "result_count": 2},
    }
    assert retrieval_state.tool_context_blocks == []

    await phase.aclose()

    assert retrieval_state.tool_context_blocks == []
    with pytest.raises(StopAsyncIteration):
        await anext(phase)


@pytest.mark.asyncio
async def test_stream_uses_crag_context_and_fallback_citations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.agents.rag_agent as rag_agent

    engine = _FakeEngine(tokens=["crag-answer"])
    runner = rag_agent.AgenticRAGRunner(engine)
    request_db = object()
    crag_calls: list[dict[str, object]] = []

    async def fake_plan(**_kwargs: object) -> list[object]:
        return [
            rag_agent.AgenticPlanStep(query="primary", rationale="plan-1"),
            rag_agent.AgenticPlanStep(query="secondary", rationale="plan-2"),
        ]

    async def fake_offload(work: Callable[[object], object], *, request_db: object) -> object:
        return work(object())

    async def fake_crag_streaming(**kwargs: object) -> dict[str, object]:
        crag_calls.append(dict(kwargs))
        return {
            "used": True,
            "provider": "web",
            "web_result_count": 3,
            "context_block": "  [crag-context]\n",
        }

    monkeypatch.setattr(runner, "_plan", fake_plan)
    monkeypatch.setattr(rag_agent, "build_rag_state", lambda **kwargs: dict(kwargs))
    monkeypatch.setattr(
        rag_agent,
        "run_retrieval",
        lambda _state: {
            "docs": [],
            "citations": [{"source": "fallback-citation"}],
            "metrics": {"retrieval_mode": "hybrid", "top_relevance_score": 0.0},
            "abstain_triggered": False,
            "abstain_reason": None,
        },
    )
    monkeypatch.setattr(rag_agent, "run_blocking_retrieval_call_with_managed_session", fake_offload)
    monkeypatch.setattr(rag_agent, "run_crag_streaming", fake_crag_streaming)
    monkeypatch.setattr(rag_agent, "build_citations_from_docs", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(rag_agent, "_build_history_text", lambda _history: "")
    monkeypatch.setattr(rag_agent, "_build_context", lambda _docs, **_kwargs: "No relevant reference materials found.")
    monkeypatch.setattr(rag_agent.settings, "RAG_MULTI_AGENT_ENABLED", False, raising=False)
    monkeypatch.setattr(rag_agent.settings, "RAG_AGENTIC_TOOLS_ENABLED", False, raising=False)
    monkeypatch.setattr(rag_agent.settings, "RAG_CRAG_STREAMING_ENABLED", True, raising=False)
    monkeypatch.setattr(rag_agent.settings, "RAG_SELF_RAG_ENABLED", False, raising=False)
    monkeypatch.setattr(rag_agent.settings, "RAG_CRITIC_ENABLED", False, raising=False)
    monkeypatch.setattr(rag_agent.settings, "RAG_AGENTIC_REFLECT_TOP_CITATIONS_MIN", 2, raising=False)
    monkeypatch.setattr(rag_agent.settings, "RAG_AGENTIC_REFLECT_TOP_SCORE_MIN", 0.95, raising=False)

    events = await _collect_events(
        runner.stream(
            request=rag_agent.AgenticStreamRequest(
                question="Need the web too?",
                db=request_db,
            )
        )
    )

    assert [event["type"] for event in events] == [
        "route",
        "agentic_step",
        "agentic_step",
        "agentic_step",
        "citations",
        "agentic_step",
        "token",
        "done",
    ]
    assert events[3]["data"] == {"step": "web_search", "provider": "web", "result_count": 3}
    assert events[4] == {"type": "citations", "data": [{"source": "fallback-citation"}]}
    assert engine._captured_inputs == [
        {
            "context": "  [crag-context]\n",
            "history": "",
            "question": "Need the web too?",
            "format_instructions": "",
        }
    ]
    assert events[-1]["data"]["metrics"]["agentic_rounds"] == 1
    assert events[-1]["data"]["metrics"]["agentic_crag_used"] is True
    assert events[-1]["data"]["metrics"]["agentic_crag_provider"] == "web"
    assert crag_calls == [
        {
            "question": "Need the web too?",
            "query_for_retrieval": "primary",
            "retrieval_result": {
                "docs": [],
                "citations": [{"source": "fallback-citation"}],
                "metrics": {"retrieval_mode": "hybrid", "top_relevance_score": 0.0},
                "abstain_triggered": False,
                "abstain_reason": None,
            },
        }
    ]
