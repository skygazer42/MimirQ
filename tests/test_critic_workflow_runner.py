from __future__ import annotations

import pytest

from app.rag.workflows.critic import CriticWorkflow


@pytest.mark.asyncio
async def test_critic_workflow_returns_structured_critique_in_state() -> None:
    workflow = CriticWorkflow()

    result = await workflow.run(
        {
            "question": "How do I configure MQTT keepalive?",
            "answer": "Use the MQTT keepalive value from the broker connection settings.",
            "context": "Use the MQTT keepalive value from the broker connection settings.",
            "citations": [{"document_id": "doc-1", "chunk_id": "chunk-1"}],
        }
    )

    assert result.success is True
    assert result.state["critique"]["schema"] == "mimirq.critic_review.v1"
    assert result.state["critique"]["verdict"] == "accept"
    assert result.state["answer"] == "Use the MQTT keepalive value from the broker connection settings."
    assert result.metadata["critic_verdict"] == "accept"


@pytest.mark.asyncio
async def test_critic_workflow_fails_when_answer_is_missing() -> None:
    workflow = CriticWorkflow()

    result = await workflow.run(
        {
            "question": "How do I configure MQTT keepalive?",
            "context": "Use the MQTT keepalive value from the broker connection settings.",
            "citations": [{"document_id": "doc-1", "chunk_id": "chunk-1"}],
        }
    )

    assert result.success is False
    assert result.error == "critic_answer_missing"
