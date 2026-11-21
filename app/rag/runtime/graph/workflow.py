"""Assemble the functional and state-graph RAG workflows."""

import logging
from functools import partial
from typing import Any
from uuid import UUID, uuid4

from langgraph.func import entrypoint
from langgraph.graph import END, StateGraph
from langgraph.runtime import Runtime

from app.infrastructure.config import settings
from app.rag.runtime.checkpoints.factory import get_checkpointer
from app.rag.runtime.graph.generation import _generate_node
from app.rag.runtime.graph.state import RAGRuntimeContext, RAGState, build_rag_state
from app.rag.runtime.graph.tasks import (
    _RAG_TASK_RETRY_POLICY,
    _retrieve_node,
    _run_corrective_loop,
    _run_with_retry,
    generate_task,
    retrieve_task,
)
from app.rag.runtime.store import get_langgraph_store

logger = logging.getLogger("rag.pipelines.langgraph")


@entrypoint(checkpointer=get_checkpointer(), store=get_langgraph_store(), context_schema=RAGRuntimeContext)
def rag_workflow(state: dict[str, Any], runtime: Runtime[RAGRuntimeContext]) -> dict[str, Any]:
    """
    RAG workflow entrypoint - using Functional API @entrypoint decorator.

    Executes retrieve -> generate flow with checkpoint persistence support.
    """
    # Execute retrieval task
    metrics = dict(state.get("metrics") or {})
    if runtime and getattr(runtime, "context", None):
        ctx = runtime.context
        if ctx.request_id:
            metrics["request_id"] = ctx.request_id
        if ctx.conversation_id:
            metrics["conversation_id"] = ctx.conversation_id
        if ctx.tenant_id:
            metrics["tenant_id"] = ctx.tenant_id
        if ctx.account_id:
            metrics["account_id"] = ctx.account_id
        if ctx.user_role:
            metrics["user_role"] = ctx.user_role
    if metrics:
        state["metrics"] = metrics

    state = _run_corrective_loop(
        state,
        retrieve_fn=lambda s: retrieve_task(s).result(),
        generate_fn=lambda s: generate_task(s).result(),
    )

    return state


def _graph_run_config(thread_id: str | None) -> dict[str, Any]:
    return {
        "configurable": {"thread_id": thread_id or f"rag-{uuid4()}"},
        "recursion_limit": max(1, int(settings.LANGGRAPH_RECURSION_LIMIT)),
    }


def run_rag_workflow_functional(
    state: dict[str, Any],
    *,
    thread_id: str | None = None,
    stream_mode: str | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Execute RAG workflow using Functional API.

    Args:
        state: RAG state dictionary
        thread_id: Optional thread ID for session persistence
        stream_mode: Streaming mode ("updates", "values", None)

    Returns:
        Execution result state
    """
    state = dict(state)
    state.pop("db", None)
    config = _graph_run_config(thread_id)

    if stream_mode:
        # Streaming execution
        result = None
        for step in rag_workflow.stream(state, config=config, stream_mode=stream_mode, context=context):
            result = step
        return result or state
    else:
        # Synchronous execution
        return rag_workflow.invoke(state, config=config, context=context)


def build_rag_graph() -> Any:
    """Build a minimal RAG flow graph: retrieve -> generate -> end."""
    if settings.LANGGRAPH_USE_SUBGRAPHS:
        return build_rag_graph_subgraphs()

    graph = StateGraph(RAGState)

    graph.add_node(
        "retrieve",
        partial(_run_with_retry, "retrieve", _retrieve_node),
        retry_policy=_RAG_TASK_RETRY_POLICY,
    )
    graph.add_node(
        "generate",
        partial(_run_with_retry, "generate", _generate_node),
        retry_policy=_RAG_TASK_RETRY_POLICY,
    )
    graph.set_entry_point("retrieve")
    graph.add_edge("retrieve", "generate")
    graph.add_edge("generate", END)

    checkpointer = get_checkpointer()
    store = get_langgraph_store()
    return graph.compile(checkpointer=checkpointer, store=store)


def _build_retrieve_subgraph() -> Any:
    """Subgraph: retrieve only (END after retrieval)."""
    g = StateGraph(RAGState)
    g.add_node(
        "retrieve",
        partial(_run_with_retry, "retrieve", _retrieve_node),
        retry_policy=_RAG_TASK_RETRY_POLICY,
    )
    g.set_entry_point("retrieve")
    g.add_edge("retrieve", END)
    return g.compile(name="rag_retrieve_subgraph")


def _build_generate_subgraph() -> Any:
    """Subgraph: generate only (END after generation)."""
    g = StateGraph(RAGState)
    g.add_node(
        "generate",
        partial(_run_with_retry, "generate", _generate_node),
        retry_policy=_RAG_TASK_RETRY_POLICY,
    )
    g.set_entry_point("generate")
    g.add_edge("generate", END)
    return g.compile(name="rag_generate_subgraph")


def build_rag_graph_subgraphs() -> Any:
    """
    Build a modular RAG graph using LangGraph subgraphs.

    This enables composition of reusable subgraphs (retrieve/generate/…)
    and mirrors the reference project's "subgraph as node" pattern.
    """
    retrieve_subgraph = _build_retrieve_subgraph()
    generate_subgraph = _build_generate_subgraph()

    g = StateGraph(RAGState)
    g.add_node("retrieve_flow", retrieve_subgraph)
    g.add_node("generate_flow", generate_subgraph)
    g.set_entry_point("retrieve_flow")
    g.add_edge("retrieve_flow", "generate_flow")
    g.add_edge("generate_flow", END)

    checkpointer = get_checkpointer()
    store = get_langgraph_store()
    return g.compile(checkpointer=checkpointer, store=store, name="rag_graph_subgraphs")


def run_rag_graph(
    question: str,
    history: list[dict[str, str]] | None = None,
    document_ids: list[UUID] | None = None,
    *,
    thread_id: str | None = None,
    runtime_context: dict[str, Any] | None = None,
    **state_fields: Any,
) -> dict[str, Any]:
    """Execute LangGraph RAG flow, return answer/citations/model info."""
    state = build_rag_state(
        question=question,
        history=history or [],
        document_ids=document_ids,
        **state_fields,
    )

    # Use Functional API (LangGraph 1.0+)
    use_functional_api = bool(settings.LANGGRAPH_USE_FUNCTIONAL_API)

    if use_functional_api:
        result = run_rag_workflow_functional(state, thread_id=thread_id, context=runtime_context)
        logger.debug("RAG workflow executed using Functional API")
    else:
        app = build_rag_graph()
        result = app.invoke(state, config=_graph_run_config(thread_id), context=runtime_context)

    return {
        "answer": result["answer"],
        "citations": result.get("citations", []),
        "model_used": result.get("model_used"),
        "route": result.get("route"),
        "routing_reason": result.get("routing_reason"),
        "metrics": result.get("metrics", {}),
    }
