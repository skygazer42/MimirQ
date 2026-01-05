"""
Workflow patterns module for RAG pipelines.

Provides 6 workflow patterns:
- Chain: Sequential step-by-step execution
- Routing: Dynamic routing based on query classification
- Parallelization: Concurrent execution with result aggregation
- ReAct: Reasoning and Acting loop
- Planner-Worker: Task decomposition and execution
- Evaluator-Optimizer: Iterative improvement loop

Usage:
    from app.rag.workflows import get_workflow, WorkflowMode

    workflow = get_workflow(WorkflowMode.CHAIN)
    result = await workflow.run(state)
"""

from app.rag.workflows.base import BaseWorkflow, WorkflowMode
from app.rag.workflows.chain import ChainWorkflow
from app.rag.workflows.routing import RoutingWorkflow
from app.rag.workflows.parallelization import ParallelWorkflow
from app.rag.workflows.react import ReActWorkflow
from app.rag.workflows.planner_worker import PlannerWorkerWorkflow
from app.rag.workflows.evaluator_optimizer import EvaluatorOptimizerWorkflow
from app.rag.workflows.factory import get_workflow, create_workflow

__all__ = [
    # Base
    "BaseWorkflow",
    "WorkflowMode",
    # Implementations
    "ChainWorkflow",
    "RoutingWorkflow",
    "ParallelWorkflow",
    "ReActWorkflow",
    "PlannerWorkerWorkflow",
    "EvaluatorOptimizerWorkflow",
    # Factory
    "get_workflow",
    "create_workflow",
]
