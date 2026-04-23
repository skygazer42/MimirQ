from __future__ import annotations

import pytest

from app.rag.workflows.self_route import SelfRouteWorkflow, route_self_query


def test_route_self_query_prefers_long_context_when_decision_text_says_so() -> None:
    out = route_self_query(
        question="Summarize the full document in detail.",
        decision_text="Use long_context because the answer needs broad document coverage.",
    )

    assert out["schema"] == "mimirq.self_route.v1"
    assert out["route"] == "long_context"
    assert out["retrieval_profile"] == "long_context"
    assert "llm_decision_long_context" in out["reason_codes"]


def test_route_self_query_falls_back_to_rag_for_multi_hop_queries() -> None:
    out = route_self_query(
        question="根据报警和维修记录分析为什么 485 总线掉线？",
        decision_text=None,
    )

    assert out["route"] == "rag"
    assert out["retrieval_profile"] == "hybrid_ce"
    assert "complexity_multi_hop" in out["reason_codes"]


@pytest.mark.asyncio
async def test_self_route_workflow_writes_route_decision_into_state() -> None:
    workflow = SelfRouteWorkflow()

    result = await workflow.run(
        {
            "question": "Summarize the full document in detail.",
            "route_decision_text": "Choose long_context for end-to-end document synthesis.",
        }
    )

    assert result.success is True
    assert result.state["route_decision"]["route"] == "long_context"
    assert result.metadata["route"] == "long_context"
