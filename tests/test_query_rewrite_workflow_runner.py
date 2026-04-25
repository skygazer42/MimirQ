from __future__ import annotations

import pytest

from app.rag.workflows.query_rewrite import QueryRewriteWorkflow, run_query_rewrite_workflow


def test_run_query_rewrite_workflow_uses_rewriter_and_emits_metadata() -> None:
    out = run_query_rewrite_workflow(
        question="it?",
        history_text="Earlier we talked about Retry-After and 429.",
        strategy_id="kb_followup.v2",
        rewriter=lambda question, history_text, strategy_id: "Retry-After header meaning",
    )

    assert out["schema"] == "mimirq.query_rewrite_workflow.v1"
    assert out["original"] == "it?"
    assert out["rewritten"] == "Retry-After header meaning"
    assert out["used"] is True
    assert out["strategy_id"] == "kb_followup.v2"
    assert isinstance(out["strategy_hash"], str) and len(out["strategy_hash"]) >= 8


def test_run_query_rewrite_workflow_falls_back_when_rewriter_returns_blank() -> None:
    out = run_query_rewrite_workflow(
        question="What is MQTT?",
        history_text="",
        strategy_id="kb_followup.v1",
        rewriter=lambda *_args, **_kwargs: "",
    )

    assert out["rewritten"] == "What is MQTT?"
    assert out["used"] is False


@pytest.mark.asyncio
async def test_query_rewrite_workflow_writes_rewrite_payload_into_state() -> None:
    workflow = QueryRewriteWorkflow()
    result = await workflow.run(
        {
            "question": "it?",
            "history_text": "Earlier we talked about Retry-After and 429.",
            "query_rewriter": lambda question, history_text, strategy_id: "Retry-After header meaning",
            "query_rewrite_strategy": "kb_followup.v2",
        }
    )

    assert result.success is True
    assert result.state["rewrite"]["rewritten"] == "Retry-After header meaning"
    assert result.state["query_for_retrieval"] == "Retry-After header meaning"
    assert result.metadata["used"] is True
