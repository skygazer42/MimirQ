from __future__ import annotations


def test_react_workflow_can_register_hierarchical_retrieval_tools() -> None:
    from app.rag.workflows.react import ReActWorkflow

    workflow = ReActWorkflow(llm=object())
    workflow.register_hierarchical_retrieval_tools(
        dataset_id="ds-1",
        account_id="u",
    )

    assert set(workflow._tools) >= {"keyword_search", "semantic_search", "chunk_read"}
