from __future__ import annotations

import uuid

import pytest


@pytest.mark.asyncio
async def test_agentic_runner_uses_crag_streaming_after_abstain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app.rag.agents.rag_agent as rag_agent_mod
    from app.core.config import settings
    from app.rag.agents.rag_agent import AgenticPlanStep, AgenticRAGRunner
    from app.rag.engine import RAGEngine

    monkeypatch.setattr(settings, "LLM_MOCK_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "LLM_MOCK_RESPONSE", "crag-backed answer", raising=False)
    monkeypatch.setattr(settings, "LLM_API_KEY", "", raising=False)
    monkeypatch.setattr(settings, "RAG_CRAG_STREAMING_ENABLED", True, raising=False)

    engine = RAGEngine()
    runner = AgenticRAGRunner(engine=engine)

    async def _fake_plan(*_args, **_kwargs):  # noqa: ANN003
        return [AgenticPlanStep(query="focused retrieval query", rationale="Need corrective retrieval.")]

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
    async def _fake_crag_streaming(**_kwargs):  # noqa: ANN003
        return {
            "used": True,
            "verdict": "incorrect",
            "provider": "serper",
            "web_result_count": 1,
            "context_block": "[Web Search]\nPLC Alarm Guide\nhttps://example.com/plc",
        }

    monkeypatch.setattr(rag_agent_mod, "run_crag_streaming", _fake_crag_streaming, raising=True)

    events: list[dict[str, object]] = []
    agen = runner.stream(
        question="How do I troubleshoot a PLC alarm?",
        history=[],
        conversation_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        account_id="u",
        document_ids=[uuid.uuid4()],
        dataset_id=uuid.uuid4(),
        top_k=3,
        score_threshold=0.0,
        retrieval_mode="vector",
        request_id="agentic-crag-test",
    )

    async for event in agen:
        events.append(event)
        if event.get("type") == "done":
            break

    done_metrics = (events[-1].get("data") or {}).get("metrics") or {}
    assert done_metrics.get("agentic_crag_used") is True
    assert done_metrics.get("agentic_crag_provider") == "serper"
    assert done_metrics.get("agentic_crag_web_results") == 1
