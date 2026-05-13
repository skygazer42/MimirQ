"""
Workflow factory for creating workflow instances.

Provides factory functions and configuration-based workflow selection.
"""


from typing import Any

from app.core.config import settings
from app.rag.core.logging import get_logger
from app.rag.workflows.base import BaseWorkflow, WorkflowMode
from app.rag.workflows.chain import ChainWorkflow
from app.rag.workflows.evaluator_optimizer import EvaluatorOptimizerWorkflow
from app.rag.workflows.parallelization import ParallelWorkflow
from app.rag.workflows.planner_worker import PlannerWorkerWorkflow
from app.rag.workflows.react import ReActWorkflow
from app.rag.workflows.routing import RoutingWorkflow

logger = get_logger("rag.workflows.factory")

# Configuration
WORKFLOW_MODE = getattr(settings, "WORKFLOW_MODE", "chain")


# Registry of workflow classes
WORKFLOW_REGISTRY: dict[WorkflowMode, type] = {
    WorkflowMode.CHAIN: ChainWorkflow,
    WorkflowMode.ROUTING: RoutingWorkflow,
    WorkflowMode.PARALLEL: ParallelWorkflow,
    WorkflowMode.REACT: ReActWorkflow,
    WorkflowMode.PLANNER: PlannerWorkerWorkflow,
    WorkflowMode.EVALUATOR: EvaluatorOptimizerWorkflow,
}

# String aliases for modes
MODE_ALIASES: dict[str, WorkflowMode] = {
    "chain": WorkflowMode.CHAIN,
    "sequential": WorkflowMode.CHAIN,
    "routing": WorkflowMode.ROUTING,
    "router": WorkflowMode.ROUTING,
    "parallel": WorkflowMode.PARALLEL,
    "parallelization": WorkflowMode.PARALLEL,
    "fan-out": WorkflowMode.PARALLEL,
    "react": WorkflowMode.REACT,
    "reasoning": WorkflowMode.REACT,
    "planner": WorkflowMode.PLANNER,
    "planner-worker": WorkflowMode.PLANNER,
    "orchestrator-worker": WorkflowMode.PLANNER,
    "evaluator": WorkflowMode.EVALUATOR,
    "evaluator-optimizer": WorkflowMode.EVALUATOR,
    "optimizer": WorkflowMode.EVALUATOR,
}


def resolve_mode(mode: str | WorkflowMode) -> WorkflowMode:
    """
    Resolve a mode string or enum to WorkflowMode.

    Args:
        mode: Mode string or enum

    Returns:
        WorkflowMode enum value

    Raises:
        ValueError: If mode is not recognized
    """
    if isinstance(mode, WorkflowMode):
        return mode

    normalized = str(mode).lower().strip()
    if normalized in MODE_ALIASES:
        return MODE_ALIASES[normalized]

    # Try direct enum match
    try:
        return WorkflowMode(normalized)
    except ValueError:
        pass

    valid_modes = list(MODE_ALIASES.keys())
    raise ValueError(
        f"Unknown workflow mode: '{mode}'. "
        f"Valid modes: {valid_modes}"
    )


def create_workflow(
    mode: str | WorkflowMode,
    **kwargs,
) -> BaseWorkflow:
    """
    Create a workflow instance for the specified mode.

    Args:
        mode: Workflow mode (string or enum)
        **kwargs: Additional configuration for the workflow

    Returns:
        Configured workflow instance

    Raises:
        ValueError: If mode is not recognized
    """
    resolved_mode = resolve_mode(mode)
    workflow_cls = WORKFLOW_REGISTRY.get(resolved_mode)

    if workflow_cls is None:
        raise ValueError(f"No workflow registered for mode: {resolved_mode}")

    logger.debug("Creating %s workflow", resolved_mode.value)
    return workflow_cls(**kwargs)


def get_workflow(
    mode: str | WorkflowMode | None = None,
    **kwargs,
) -> BaseWorkflow:
    """
    Get a workflow instance, using config default if mode not specified.

    Args:
        mode: Optional workflow mode (uses config default if None)
        **kwargs: Additional configuration

    Returns:
        Configured workflow instance
    """
    if mode is None:
        mode = WORKFLOW_MODE

    return create_workflow(mode, **kwargs)


def get_default_mode() -> WorkflowMode:
    """Get the default workflow mode from configuration."""
    return resolve_mode(WORKFLOW_MODE)


def list_available_modes() -> dict[str, str]:
    """
    List all available workflow modes with descriptions.

    Returns:
        Dict mapping mode name to description
    """
    return {
        "chain": "Sequential step-by-step execution",
        "routing": "Dynamic routing based on query classification",
        "parallel": "Concurrent execution with result aggregation",
        "react": "Reasoning and Acting loop for complex queries",
        "planner": "Task decomposition and parallel execution",
        "evaluator": "Iterative improvement with quality evaluation",
    }


# Convenience functions for common patterns


def create_rag_workflow(
    retrieve_func: Any,
    generate_func: Any,
    mode: str | WorkflowMode = "chain",
    **kwargs,
) -> BaseWorkflow:
    """
    Create a standard RAG workflow.

    Args:
        retrieve_func: Retrieval function
        generate_func: Generation function
        mode: Workflow mode
        **kwargs: Additional configuration

    Returns:
        Configured workflow
    """
    resolved_mode = resolve_mode(mode)

    if resolved_mode == WorkflowMode.CHAIN:
        from app.rag.workflows.chain import create_rag_chain
        return create_rag_chain(retrieve_func, generate_func, **kwargs)

    elif resolved_mode == WorkflowMode.PARALLEL:
        workflow = ParallelWorkflow(**kwargs)
        workflow.add_task("retrieve", retrieve_func)
        return workflow

    else:
        # For other modes, create basic workflow
        return create_workflow(mode, **kwargs)


def create_multi_query_workflow(
    retrieve_func: Any,
    query_rewrite_func: Any,
    generate_func: Any,
    num_queries: int = 3,
    **kwargs,
) -> ParallelWorkflow:
    """
    Create a multi-query parallel retrieval workflow.

    Args:
        retrieve_func: Retrieval function
        query_rewrite_func: Query rewriting function
        generate_func: Generation function
        num_queries: Number of query variations
        **kwargs: Additional configuration

    Returns:
        Configured ParallelWorkflow
    """
    _ = generate_func

    from app.rag.workflows.parallelization import create_multi_query_aggregator

    def create_query_task(query_id: int):
        async def task(state: dict[str, Any]) -> dict[str, Any]:
            question = state.get("question") or state.get("query") or ""
            # Rewrite query
            rewritten = await query_rewrite_func(question, query_id)
            # Retrieve
            contexts = await retrieve_func(rewritten)
            return {"contexts": contexts, "rewritten_query": rewritten}
        return task

    # Create workflow with aggregator
    aggregator = create_multi_query_aggregator()

    workflow = ParallelWorkflow(aggregator=aggregator, **kwargs)

    for i in range(num_queries):
        workflow.add_task(f"query_{i}", create_query_task(i))

    return workflow
