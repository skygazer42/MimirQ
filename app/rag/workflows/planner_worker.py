"""
Planner-Worker Workflow Pattern.

Task decomposition and parallel/sequential execution.
A planner breaks down complex tasks, workers execute subtasks.

Pattern: Plan -> [Worker1, Worker2, ...] -> Synthesize -> Result
"""

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from app.rag.core.logging import get_logger
from app.rag.workflows.base import (
    BaseWorkflow,
    WorkflowMode,
    WorkflowResult,
)

logger = get_logger("rag.workflows.planner_worker")


class SubTask:
    """A subtask created by the planner."""

    def __init__(
        self,
        id: str,
        description: str,
        dependencies: list[str] | None = None,
    ):
        self.id = id
        self.description = description
        self.dependencies = dependencies or []
        self.result: str | None = None
        self.completed: bool = False


class PlannerWorkerWorkflow(BaseWorkflow):
    """
    Planner-Worker workflow decomposes complex tasks.

    The planner creates a plan of subtasks, workers execute
    each subtask, and results are synthesized into a final answer.

    Usage:
        workflow = PlannerWorkerWorkflow(llm=my_llm)
        workflow.set_worker(my_worker_func)
        result = await workflow.run({"question": "..."})
    """

    def __init__(
        self,
        llm: Any | None = None,
        max_subtasks: int = 5,
        parallel_execution: bool = True,
        **kwargs,
    ):
        """
        Initialize the planner-worker workflow.

        Args:
            llm: Language model for planning and synthesis
            max_subtasks: Maximum number of subtasks
            parallel_execution: Execute independent subtasks in parallel
            **kwargs: Additional configuration
        """
        super().__init__(**kwargs)
        self._llm = llm
        self._worker: Callable[[str], Awaitable[str]] | None = None
        self.max_subtasks = max_subtasks
        self.parallel_execution = parallel_execution

    @property
    def mode(self) -> WorkflowMode:
        return WorkflowMode.PLANNER

    def set_llm(self, llm: Any) -> "PlannerWorkerWorkflow":
        """Set the language model."""
        self._llm = llm
        return self

    def set_worker(
        self,
        worker: Callable[[str], Awaitable[str]],
    ) -> "PlannerWorkerWorkflow":
        """
        Set the worker function.

        The worker receives a subtask description and returns a result.
        """
        self._worker = worker
        return self

    async def _plan(self, question: str) -> list[SubTask]:
        """
        Create a plan of subtasks.

        Args:
            question: Original question

        Returns:
            List of SubTasks
        """
        if self._llm is None:
            raise ValueError("LLM not configured")

        prompt = f"""You are a task planner. Break down the following question into smaller, focused subtasks.

Question: {question}

Create a plan with up to {self.max_subtasks} subtasks. For each subtask:
1. Give it a unique ID (task1, task2, etc.)
2. Describe what needs to be done
3. List any dependencies (other task IDs that must complete first)

Format your response as:
task1: [description] | deps: none
task2: [description] | deps: task1
task3: [description] | deps: none

Plan:"""

        response = await self._llm.ainvoke(prompt)
        content = response.content if hasattr(response, "content") else str(response)

        # Parse subtasks
        subtasks = []
        for line in content.strip().split("\n"):
            line = line.strip()
            if not line or ":" not in line:
                continue

            parts = line.split(":", 1)
            if len(parts) != 2:
                continue

            task_id = parts[0].strip()
            rest = parts[1].strip()

            # Parse dependencies
            deps = []
            if "|" in rest:
                desc_part, deps_part = rest.rsplit("|", 1)
                description = desc_part.strip()
                deps_str = deps_part.replace("deps:", "").strip()
                if deps_str and deps_str.lower() != "none":
                    deps = [d.strip() for d in deps_str.split(",") if d.strip()]
            else:
                description = rest

            if description:
                subtasks.append(SubTask(task_id, description, deps))

        return subtasks[: self.max_subtasks]

    async def _execute_worker(self, subtask: SubTask) -> str:
        """Execute a subtask using the worker."""
        if self._worker is None:
            return f"No worker configured for: {subtask.description}"

        try:
            return await self._worker(subtask.description)
        except Exception as e:
            logger.exception("Worker failed for %s: %s", subtask.id, e)
            return f"Error: {str(e)}"

    async def _execute_subtasks(self, subtasks: list[SubTask]) -> dict[str, str]:
        """
        Execute subtasks respecting dependencies.

        Returns:
            Dict mapping task_id to result
        """
        results: dict[str, str] = {}
        completed: set = set()

        while len(completed) < len(subtasks):
            # Find tasks ready to execute
            ready = [t for t in subtasks if t.id not in completed and all(d in completed for d in t.dependencies)]

            if not ready:
                # No tasks ready - might have circular deps
                remaining = [t for t in subtasks if t.id not in completed]
                for t in remaining:
                    results[t.id] = "Error: Circular dependency"
                    completed.add(t.id)
                break

            if self.parallel_execution:
                # Execute ready tasks in parallel
                async def run_task(task: SubTask) -> tuple:
                    result = await self._execute_worker(task)
                    return task.id, result

                task_results = await asyncio.gather(*[run_task(t) for t in ready])
                for task_id, result in task_results:
                    results[task_id] = result
                    completed.add(task_id)
            else:
                # Execute sequentially
                for task in ready:
                    result = await self._execute_worker(task)
                    results[task.id] = result
                    completed.add(task.id)

        return results

    async def _synthesize(
        self,
        question: str,
        subtasks: list[SubTask],
        results: dict[str, str],
    ) -> str:
        """
        Synthesize subtask results into a final answer.

        Args:
            question: Original question
            subtasks: List of subtasks
            results: Subtask results

        Returns:
            Final synthesized answer
        """
        if self._llm is None:
            # Simple concatenation
            parts = [f"{t.id}: {results.get(t.id, 'No result')}" for t in subtasks]
            return "\n".join(parts)

        # Format subtask results
        result_text = []
        for task in subtasks:
            result = results.get(task.id, "No result")
            result_text.append(f"Subtask '{task.description}':\n{result}")

        prompt = f"""You are synthesizing answers from multiple subtasks to answer the original question.

Original Question: {question}

Subtask Results:
{chr(10).join(result_text)}

Based on all the subtask results above, provide a comprehensive answer to the original question.

Final Answer:"""

        response = await self._llm.ainvoke(prompt)
        return response.content if hasattr(response, "content") else str(response)

    async def run(self, state: dict[str, Any]) -> WorkflowResult:
        """
        Execute the planner-worker workflow.

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

        question = self.get_question(state)
        current_state = dict(state)
        execution_path: list[str] = ["plan"]

        # Plan
        try:
            subtasks = await self._plan(question)
            current_state["plan"] = [
                {"id": t.id, "description": t.description, "dependencies": t.dependencies} for t in subtasks
            ]
            execution_path.append(f"planned:{len(subtasks)}_tasks")
        except Exception as e:
            logger.exception("Planning failed: %s", e)
            return self.create_result(
                current_state,
                success=False,
                error=f"Planning failed: {e}",
                execution_path=execution_path,
            )

        if not subtasks:
            return self.create_result(
                current_state,
                success=False,
                error="No subtasks generated",
                execution_path=execution_path,
            )

        # Execute
        try:
            results = await self._execute_subtasks(subtasks)
            current_state["subtask_results"] = results
            for task_id in results:
                execution_path.append(f"worker:{task_id}")
        except Exception as e:
            logger.exception("Execution failed: %s", e)
            return self.create_result(
                current_state,
                success=False,
                error=f"Execution failed: {e}",
                execution_path=execution_path,
            )

        # Synthesize
        execution_path.append("synthesize")
        try:
            answer = await self._synthesize(question, subtasks, results)
            current_state["answer"] = answer

            return self.create_result(
                current_state,
                success=True,
                execution_path=execution_path,
                iterations=len(subtasks),
                metadata={"subtasks": len(subtasks)},
            )

        except Exception as e:
            logger.exception("Synthesis failed: %s", e)
            return self.create_result(
                current_state,
                success=False,
                error=f"Synthesis failed: {e}",
                execution_path=execution_path,
            )


def create_rag_worker(
    retrieve_func: Callable[[str], Awaitable[list[dict[str, Any]]]],
    generate_func: Callable[[str, list[dict[str, Any]]], Awaitable[str]],
) -> Callable[[str], Awaitable[str]]:
    """
    Create a RAG-based worker function.

    Args:
        retrieve_func: Retrieval function
        generate_func: Generation function

    Returns:
        Worker function
    """

    async def worker(subtask: str) -> str:
        # Retrieve relevant context
        contexts = await retrieve_func(subtask)

        # Generate answer
        answer = await generate_func(subtask, contexts)
        return answer

    return worker
