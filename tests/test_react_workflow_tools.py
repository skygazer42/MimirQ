from __future__ import annotations

import pytest


def test_react_workflow_can_register_hierarchical_retrieval_tools() -> None:
    from app.rag.workflows.react import ReActWorkflow

    workflow = ReActWorkflow(llm=object())
    workflow.register_hierarchical_retrieval_tools(
        dataset_id="ds-1",
        account_id="u",
    )

    assert set(workflow._tools) >= {"keyword_search", "semantic_search", "chunk_read"}


@pytest.mark.asyncio
async def test_react_workflow_can_register_retrieval_config_tool() -> None:
    from app.rag.workflows.react import ReActWorkflow

    workflow = ReActWorkflow(llm=object())
    workflow.register_retrieval_config_tool()

    assert "configure_retrieval" in workflow._tools
    result = await workflow._tools["configure_retrieval"].invoke('{"top_k": 5, "reranker_top_n": 3, "retrieval_profile": "hybrid_ce"}')
    assert "hybrid_ce" in result
    assert "cross_encoder" in result
