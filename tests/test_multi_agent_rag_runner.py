from __future__ import annotations

import threading
import time
import uuid

import pytest
from langchain_core.documents import Document


@pytest.mark.asyncio
async def test_multi_agent_runner_executes_sub_questions_in_parallel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.agents.multi_agent as multi_agent_mod
    from app.core.config import settings
    from app.rag.agents.multi_agent import MultiAgentPlanStep, MultiAgentRAGRunner
    from app.rag.engine import RAGEngine

    monkeypatch.setattr(settings, "LLM_MOCK_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "LLM_MOCK_RESPONSE", "parallel synthesized answer", raising=False)
    monkeypatch.setattr(settings, "LLM_API_KEY", "", raising=False)

    engine = RAGEngine()
    runner = MultiAgentRAGRunner(engine=engine)

    async def _fake_decompose(*_args, **_kwargs):  # noqa: ANN003
        return [
            MultiAgentPlanStep(query="sub-question one", rationale="part_one"),
            MultiAgentPlanStep(query="sub-question two", rationale="part_two"),
        ]

    monkeypatch.setattr(runner, "_decompose", _fake_decompose, raising=True)

    active_calls = 0
    max_parallel_calls = 0
    lock = threading.Lock()

    def _doc(question: str, chunk_id: str, score: float) -> Document:
        return Document(
            page_content=f"{question} evidence {chunk_id}",
            id=chunk_id,
            metadata={
                "document_id": chunk_id.split(":")[0],
                "chunk_id": chunk_id,
                "chunk_index": int(chunk_id.split(":")[1]),
                "source": f"{chunk_id}.txt",
                "page": 1,
                "score": score,
                "relevance_score": score,
            },
        )

    def _fake_run_retrieval(state: dict[str, object]) -> dict[str, object]:
        nonlocal active_calls, max_parallel_calls
        question = str(state.get("question") or "")
        with lock:
            active_calls += 1
            max_parallel_calls = max(max_parallel_calls, active_calls)
        time.sleep(0.05)
        with lock:
            active_calls -= 1

        shared = _doc(question, "doc-shared:0", 0.8)
        unique = _doc(question, f"doc-{question[-3:]}:0", 0.9)
        citations = [
            {
                "document_id": "doc-shared",
                "chunk_id": "doc-shared:0",
                "page_number": 1,
                "source": "doc-shared:0.txt",
                "snippet": "shared evidence",
                "relevance_score": 0.8,
            },
            {
                "document_id": unique.metadata["document_id"],
                "chunk_id": unique.metadata["chunk_id"],
                "page_number": 1,
                "source": unique.metadata["source"],
                "snippet": unique.page_content,
                "relevance_score": 0.9,
            },
        ]
        return {
            "docs": [shared, unique],
            "citations": citations,
            "metrics": {"retrieval_mode": "vector", "top_relevance_score": 0.9},
            "abstain_triggered": False,
            "abstain_reason": None,
        }

    monkeypatch.setattr(multi_agent_mod, "run_retrieval", _fake_run_retrieval, raising=True)

    events: list[dict[str, object]] = []
    agen = runner.stream(
        question="Compare two complex aspects and synthesize them.",
        history=[],
        conversation_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        account_id="u",
        document_ids=[uuid.uuid4()],
        top_k=3,
        score_threshold=0.0,
        retrieval_mode="vector",
        request_id="multi-agent-runner-test",
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
    assert max_parallel_calls >= 2

    citations = next(event["data"] for event in events if event.get("type") == "citations")
    assert isinstance(citations, list)
    assert len(citations) == 3

    done_metrics = (events[-1].get("data") or {}).get("metrics") or {}
    assert done_metrics.get("agentic_used") is True
    assert done_metrics.get("agentic_planned_steps") == 2
    assert done_metrics.get("agentic_rounds") == 2
    assert done_metrics.get("docs_returned") == 3
