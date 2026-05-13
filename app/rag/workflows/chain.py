"""
Chain Workflow Pattern.

Sequential step-by-step execution where each step's output
becomes the next step's input.

Pattern: Step1 -> Step2 -> Step3 -> ... -> Result
"""


from collections.abc import Awaitable, Callable
from typing import Any

from app.rag.core.logging import get_logger
from app.rag.workflows.base import (
    BaseWorkflow,
    WorkflowMode,
    WorkflowResult,
    WorkflowStep,
)

logger = get_logger("rag.workflows.chain")


class ChainWorkflow(BaseWorkflow):
    """
    Chain workflow executes steps sequentially.

    Each step receives the output of the previous step.
    The workflow stops if any step fails or returns an error.

    Usage:
        workflow = ChainWorkflow()
        workflow.add_step("retrieve", retrieve_func)
        workflow.add_step("generate", generate_func)
        result = await workflow.run({"question": "..."})
    """

    def __init__(
        self,
        steps: list[WorkflowStep] | None = None,
        stop_on_error: bool = True,
        **kwargs,
    ):
        """
        Initialize the chain workflow.

        Args:
            steps: Optional list of workflow steps
            stop_on_error: Stop execution if a step fails
            **kwargs: Additional configuration
        """
        super().__init__(**kwargs)
        self._steps: list[WorkflowStep] = steps or []
        self.stop_on_error = stop_on_error

    @property
    def mode(self) -> WorkflowMode:
        return WorkflowMode.CHAIN

    def add_step(
        self,
        name: str,
        func: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]],
        condition: Callable[[dict[str, Any]], bool] | None = None,
    ) -> "ChainWorkflow":
        """
        Add a step to the chain.

        Args:
            name: Step name
            func: Async function that transforms state
            condition: Optional condition for execution

        Returns:
            Self for chaining
        """
        self._steps.append(WorkflowStep(name, func, condition))
        return self

    def clear_steps(self) -> "ChainWorkflow":
        """Clear all steps."""
        self._steps.clear()
        return self

    async def run(self, state: dict[str, Any]) -> WorkflowResult:
        """
        Execute the chain workflow.

        Args:
            state: Initial state

        Returns:
            WorkflowResult with final state
        """
        if not self.validate_state(state):
            return self.create_result(
                state,
                success=False,
                error="Invalid state: missing question/query",
            )

        current_state = dict(state)
        execution_path: list[str] = []

        for step in self._steps:
            step_name = step.name

            # Check condition
            if not step.should_execute(current_state):
                logger.debug("Skipping step %s: condition not met", step_name)
                continue

            try:
                logger.debug("Executing step: %s", step_name)
                current_state = await step.execute(current_state)
                execution_path.append(step_name)

                # Check for error in state
                if current_state.get("error") and self.stop_on_error:
                    logger.warning("Step %s returned error: %s", step_name, current_state.get("error"))
                    return self.create_result(
                        current_state,
                        success=False,
                        error=current_state.get("error"),
                        execution_path=execution_path,
                    )

            except Exception as e:
                logger.error("Step %s failed: %s", step_name, e)
                if self.stop_on_error:
                    return self.create_result(
                        current_state,
                        success=False,
                        error=str(e),
                        execution_path=execution_path,
                    )
                else:
                    current_state["error"] = str(e)

        return self.create_result(
            current_state,
            success=True,
            execution_path=execution_path,
        )


def create_rag_chain(
    retrieve_func: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]],
    generate_func: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]],
    **kwargs,
) -> ChainWorkflow:
    """
    Create a standard RAG chain workflow.

    Args:
        retrieve_func: Retrieval function
        generate_func: Generation function
        **kwargs: Additional workflow config

    Returns:
        Configured ChainWorkflow
    """
    workflow = ChainWorkflow(**kwargs)
    workflow.add_step("retrieve", retrieve_func)
    workflow.add_step("generate", generate_func)
    return workflow
