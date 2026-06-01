from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from langchain_core.documents import Document


@pytest.mark.asyncio
async def test_stream_chat_routes_complex_queries_to_agentic_runner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.engine as engine_mod
    from app.core.config import settings
    from app.rag.engine import RAGEngine

    class _DummyRunner:
        async def stream(self, **kwargs):  # noqa: ANN003
            yield {"type": "agentic_step", "data": {"step": "planning", "question": kwargs["question"]}}
            yield {"type": "done", "data": {"metrics": {"agentic_used": True}}}

    monkeypatch.setattr(settings, "RAG_AGENTIC_MODE_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "RAG_AGENTIC_COMPLEXITY_THRESHOLD", 50.0, raising=False)
    monkeypatch.setattr(settings, "LLM_MOCK_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "LLM_MOCK_RESPONSE", "mock answer", raising=False)
    monkeypatch.setattr(settings, "LLM_API_KEY", "", raising=False)
    monkeypatch.setattr(RAGEngine, "_score_question_complexity", lambda *_args, **_kwargs: 250.0, raising=True)
    monkeypatch.setattr(engine_mod, "get_agentic_runner", lambda *_a, **_k: _DummyRunner(), raising=False)

    engine = RAGEngine()
    events: list[dict[str, object]] = []

    agen = engine.stream_chat(
        question="Analyze the cross-document dependencies and explain the tradeoffs in detail.",
        history=[],
        tenant_id=uuid.uuid4(),
        account_id="u",
        document_ids=[uuid.uuid4()],
        top_k=3,
        score_threshold=0.0,
        retrieval_mode="vector",
        request_id="agentic-route-test",
    )

    try:
        async for event in agen:
            events.append(event)
            if event.get("type") == "done":
                break
    finally:
        await agen.aclose()

    assert [event.get("type") for event in events] == ["agentic_step", "done"]
    assert events[0]["data"]["step"] == "planning"
    assert events[1]["data"]["metrics"]["agentic_used"] is True


@pytest.mark.asyncio
async def test_agentic_runner_streams_planning_retrieval_and_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.agents.rag_agent as rag_agent_mod
    from app.core.config import settings
    from app.rag.agents.rag_agent import AgenticPlanStep, AgenticRAGRunner
    from app.rag.engine import RAGEngine

    monkeypatch.setattr(settings, "LLM_MOCK_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "LLM_MOCK_RESPONSE", "agentic answer", raising=False)
    monkeypatch.setattr(settings, "LLM_API_KEY", "", raising=False)
    monkeypatch.setattr(settings, "RAG_AGENTIC_MAX_RETRIEVE_ROUNDS", 2, raising=False)

    engine = RAGEngine()
    runner = AgenticRAGRunner(engine=engine)

    doc = Document(
        page_content="Evidence about the agentic answer.",
        id="doc-1:0",
        metadata={
            "document_id": "doc-1",
            "chunk_id": "doc-1:0",
            "chunk_index": 0,
            "source": "doc.txt",
            "page": 1,
            "score": 0.9,
            "relevance_score": 0.9,
        },
    )

    async def _fake_plan(*_args, **_kwargs):  # noqa: ANN003
        return [AgenticPlanStep(query="focused retrieval query", rationale="Focus on the strongest evidence.")]

    monkeypatch.setattr(runner, "_plan", _fake_plan, raising=True)
    monkeypatch.setattr(
        rag_agent_mod,
        "build_rag_state",
        lambda **_kwargs: {"question": "focused retrieval query", "history": [], "top_k": 3},
        raising=True,
    )
    monkeypatch.setattr(
        rag_agent_mod,
        "run_retrieval",
        lambda _state: {
            "docs": [doc],
            "citations": [
                {
                    "document_id": "doc-1",
                    "chunk_id": "doc-1:0",
                    "page_number": 1,
                    "relevance_score": 0.9,
                    "source": "doc.txt",
                    "snippet": "Evidence about the agentic answer.",
                }
            ],
            "metrics": {"retrieval_mode": "vector", "top_relevance_score": 0.9},
            "abstain_triggered": False,
            "abstain_reason": None,
        },
        raising=True,
    )

    events: list[dict[str, object]] = []
    agen = runner.stream(
        question="Analyze the evidence and explain the answer.",
        history=[],
        conversation_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        account_id="u",
        document_ids=[uuid.uuid4()],
        top_k=3,
        score_threshold=0.0,
        retrieval_mode="vector",
        request_id="agentic-runner-test",
    )

    async for event in agen:
        events.append(event)
        if event.get("type") == "done":
            break

    event_types = [event.get("type") for event in events]
    assert event_types[0] == "route"
    assert "agentic_step" in event_types
    assert "citations" in event_types
    assert "token" in event_types
    assert event_types[-1] == "done"

    done_metrics = (events[-1].get("data") or {}).get("metrics") or {}
    assert done_metrics.get("agentic_used") is True
    assert done_metrics.get("agentic_rounds") == 1
    assert done_metrics.get("agentic_planned_steps") == 1


@pytest.mark.asyncio
async def test_agentic_runner_calls_math_tool_before_answer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.agents.rag_agent as rag_agent_mod
    from app.core.config import settings
    from app.rag.agents.rag_agent import AgenticPlanStep, AgenticRAGRunner
    from app.rag.engine import RAGEngine

    monkeypatch.setattr(settings, "LLM_MOCK_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "LLM_MOCK_RESPONSE", "tool-backed answer", raising=False)
    monkeypatch.setattr(settings, "LLM_API_KEY", "", raising=False)
    monkeypatch.setattr(settings, "RAG_AGENTIC_TOOLS_ENABLED", True, raising=False)

    engine = RAGEngine()
    runner = AgenticRAGRunner(engine=engine)

    async def _fake_plan(*_args, **_kwargs):  # noqa: ANN003
        return [AgenticPlanStep(query="focused retrieval query", rationale="Follow the strongest lead.")]

    calls: list[tuple[str, dict[str, object]]] = []

    class _Registry:
        async def call_tool(self, name: str, arguments: dict[str, object]):  # noqa: ANN201
            calls.append((name, dict(arguments)))
            return SimpleNamespace(
                success=True,
                data={"expression": "2 + 2", "result": 4, "success": True},
                error=None,
                metadata={"backend": "local"},
            )

    monkeypatch.setattr(runner, "_plan", _fake_plan, raising=True)
    monkeypatch.setattr(
        rag_agent_mod,
        "build_rag_state",
        lambda **_kwargs: {"question": "focused retrieval query", "history": [], "top_k": 3},
        raising=True,
    )
    monkeypatch.setattr(
        rag_agent_mod,
        "run_retrieval",
        lambda _state: {
            "docs": [],
            "citations": [],
            "metrics": {"retrieval_mode": "vector", "top_relevance_score": 0.0},
            "abstain_triggered": True,
            "abstain_reason": "no_docs",
        },
        raising=True,
    )
    monkeypatch.setattr(rag_agent_mod, "get_agentic_tool_registry", lambda: _Registry(), raising=True)

    events: list[dict[str, object]] = []
    agen = runner.stream(
        question="What is 2 + 2?",
        history=[],
        conversation_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        account_id="u",
        document_ids=[uuid.uuid4()],
        dataset_id=uuid.uuid4(),
        top_k=3,
        score_threshold=0.0,
        retrieval_mode="vector",
        request_id="agentic-tool-test",
    )

    async for event in agen:
        events.append(event)
        if event.get("type") == "done":
            break

    assert calls == [("calculate", {"expression": "2 + 2"})]
    step_names = [event.get("data", {}).get("step") for event in events if event.get("type") == "agentic_step"]
    assert "tool_call" in step_names
    assert "tool_result" in step_names

    done_metrics = (events[-1].get("data") or {}).get("metrics") or {}
    assert done_metrics.get("agentic_tools_used") == 1
    assert done_metrics.get("agentic_tool_calls") == [
        {"name": "calculate", "success": True, "backend": "local", "error": None}
    ]


@pytest.mark.asyncio
async def test_agentic_runner_reads_single_document_with_tool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.agents.rag_agent as rag_agent_mod
    from app.core.config import settings
    from app.rag.agents.rag_agent import AgenticPlanStep, AgenticRAGRunner
    from app.rag.engine import RAGEngine

    monkeypatch.setattr(settings, "LLM_MOCK_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "LLM_MOCK_RESPONSE", "document-backed answer", raising=False)
    monkeypatch.setattr(settings, "LLM_API_KEY", "", raising=False)
    monkeypatch.setattr(settings, "RAG_AGENTIC_TOOLS_ENABLED", True, raising=False)

    engine = RAGEngine()
    runner = AgenticRAGRunner(engine=engine)
    dataset_id = uuid.uuid4()
    document_id = uuid.uuid4()
    captured: list[tuple[str, dict[str, object]]] = []

    async def _fake_plan(*_args, **_kwargs):  # noqa: ANN003
        return [AgenticPlanStep(query="focused retrieval query", rationale="Read the provided document first.")]

    class _Registry:
        async def call_tool(self, name: str, arguments: dict[str, object]):  # noqa: ANN201
            captured.append((name, dict(arguments)))
            return SimpleNamespace(
                success=True,
                data={"content": "Full document content.", "chunk_count": 1},
                error=None,
                metadata={"backend": "local"},
            )

    monkeypatch.setattr(runner, "_plan", _fake_plan, raising=True)
    monkeypatch.setattr(
        rag_agent_mod,
        "build_rag_state",
        lambda **_kwargs: {"question": "focused retrieval query", "history": [], "top_k": 3},
        raising=True,
    )
    monkeypatch.setattr(
        rag_agent_mod,
        "run_retrieval",
        lambda _state: {
            "docs": [],
            "citations": [],
            "metrics": {"retrieval_mode": "vector", "top_relevance_score": 0.0},
            "abstain_triggered": True,
            "abstain_reason": "no_docs",
        },
        raising=True,
    )
    monkeypatch.setattr(rag_agent_mod, "get_agentic_tool_registry", lambda: _Registry(), raising=True)

    events: list[dict[str, object]] = []
    agen = runner.stream(
        question="Read the full document and summarize it for me.",
        history=[],
        conversation_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        account_id="user-1",
        document_ids=[document_id],
        dataset_id=dataset_id,
        top_k=3,
        score_threshold=0.0,
        retrieval_mode="vector",
        request_id="agentic-doc-tool-test",
    )

    async for event in agen:
        events.append(event)
        if event.get("type") == "done":
            break

    assert captured == [
        (
            "get_document_content",
            {
                "document_id": str(document_id),
                "dataset_id": str(dataset_id),
                "account_id": "user-1",
            },
        )
    ]
    done_metrics = (events[-1].get("data") or {}).get("metrics") or {}
    assert done_metrics.get("agentic_tools_used") == 1


@pytest.mark.asyncio
async def test_agentic_runner_delegates_to_multi_agent_runner_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.agents.rag_agent as rag_agent_mod
    from app.core.config import settings
    from app.rag.agents.rag_agent import AgenticPlanStep, AgenticRAGRunner
    from app.rag.engine import RAGEngine

    monkeypatch.setattr(settings, "LLM_MOCK_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "LLM_MOCK_RESPONSE", "delegated answer", raising=False)
    monkeypatch.setattr(settings, "LLM_API_KEY", "", raising=False)
    monkeypatch.setattr(settings, "RAG_MULTI_AGENT_ENABLED", True, raising=False)

    engine = RAGEngine()
    runner = AgenticRAGRunner(engine=engine)

    async def _fake_plan(*_args, **_kwargs):  # noqa: ANN003
        return [
            AgenticPlanStep(query="sub-question one", rationale="part_one"),
            AgenticPlanStep(query="sub-question two", rationale="part_two"),
        ]

    class _DummyMultiRunner:
        async def stream(self, **kwargs):  # noqa: ANN003
            request = kwargs.get("request")
            question = getattr(request, "question", None) or kwargs.get("question")
            yield {"type": "route", "data": {"route": "multi_agent", "question": question}}
            yield {"type": "done", "data": {"metrics": {"agentic_used": True, "delegated": True}}}

    monkeypatch.setattr(runner, "_plan", _fake_plan, raising=True)
    monkeypatch.setattr(rag_agent_mod, "get_multi_agent_runner", lambda **_kwargs: _DummyMultiRunner(), raising=True)

    events: list[dict[str, object]] = []
    agen = runner.stream(
        question="Compare the two issues and synthesize a final answer.",
        history=[],
        conversation_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        account_id="u",
        document_ids=[uuid.uuid4()],
        dataset_id=uuid.uuid4(),
        top_k=3,
        score_threshold=0.0,
        retrieval_mode="vector",
        request_id="agentic-delegate-test",
    )

    async for event in agen:
        events.append(event)
        if event.get("type") == "done":
            break

    assert [event.get("type") for event in events] == ["route", "done"]
    assert (events[-1].get("data") or {}).get("metrics") == {"agentic_used": True, "delegated": True}
