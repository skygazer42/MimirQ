"""
Planner-Worker Workflow Pattern.

Task decomposition and parallel/sequential execution.
A planner breaks down complex tasks, workers execute subtasks.

Pattern: Plan -> [Worker1, Worker2, ...] -> Synthesize -> Result
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from app.rag.workflows.base import (
    BaseWorkflow,
    WorkflowMode,
    WorkflowPlanStep,
    WorkflowResult,
    cancel_and_drain_tasks,
    model_response_text,
)

logger = logging.getLogger("rag.workflows.planner_worker")


class SubTask:
    """A subtask created by the planner."""

    def __init__(
        self,
        id: str,
        description: str,
        dependencies: list[str] | None = None,
    ) -> None:
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
        **kwargs: Any,
    ) -> None:
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
        content = model_response_text(response)

        # Parse subtasks
        subtasks: list[SubTask] = []
        for line in content.strip().split("\n"):
            line = line.strip()
            if not line or ":" not in line:
                continue

            parts = line.split(":", 1)
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
            raise ValueError("Worker not configured")

        result = await self._worker(subtask.description)
        if not isinstance(result, str):
            raise TypeError("Worker result must be text")
        return result

    async def _execute_subtasks(self, subtasks: list[SubTask]) -> dict[str, str]:
        """
        Execute subtasks respecting dependencies.

        Returns:
            Dict mapping task_id to result
        """
        results: dict[str, str] = {}
        task_ids = {task.id for task in subtasks}
        if len(task_ids) != len(subtasks) or any(not task.id for task in subtasks):
            raise ValueError("Task IDs must be unique and non-empty")
        unknown_dependencies = {dependency for task in subtasks for dependency in task.dependencies} - task_ids
        if unknown_dependencies:
            raise ValueError(f"Unknown task dependencies: {sorted(unknown_dependencies)}")

        while len(results) < len(subtasks):
            # Find tasks ready to execute
            ready = [
                task for task in subtasks if task.id not in results and all(d in results for d in task.dependencies)
            ]

            if not ready:
                raise ValueError("Circular task dependency")

            if self.parallel_execution:
                # Execute ready tasks in parallel
                async def run_task(task: SubTask) -> tuple[str, str]:
                    result = await self._execute_worker(task)
                    return task.id, result

                tasks: list[asyncio.Task[tuple[str, str]]] = []
                pending_error: BaseException | None = None
                try:
                    for task in ready:
                        task_coro = run_task(task)
                        try:
                            tasks.append(asyncio.create_task(task_coro))
                        except BaseException:
                            task_coro.close()
                            raise
                    task_results = await asyncio.gather(*tasks)
                except BaseException as operation_error:
                    pending_error = operation_error
                    raise
                finally:
                    await cancel_and_drain_tasks(tasks, pending_error=pending_error)
                for task_id, result in task_results:
                    results[task_id] = result
            else:
                # Execute sequentially
                for task in ready:
                    result = await self._execute_worker(task)
                    results[task.id] = result

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
            parts = [f"{t.id}: {results[t.id]}" for t in subtasks]
            return "\n".join(parts)

        # Format subtask results
        result_text = []
        for task in subtasks:
            result = results[task.id]
            result_text.append(f"Subtask '{task.description}':\n{result}")

        prompt = f"""You are synthesizing answers from multiple subtasks to answer the original question.

Original Question: {question}

Subtask Results:
{chr(10).join(result_text)}

Based on all the subtask results above, provide a comprehensive answer to the original question.

Final Answer:"""

        response = await self._llm.ainvoke(prompt)
        return model_response_text(response)

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
            plan: list[WorkflowPlanStep] = [
                {"id": t.id, "description": t.description, "dependencies": t.dependencies} for t in subtasks
            ]
            current_state["plan"] = plan
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
        return await generate_func(subtask, contexts)

    return worker
