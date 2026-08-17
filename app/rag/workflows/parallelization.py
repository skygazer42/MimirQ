"""
Parallelization Workflow Pattern.

Concurrent execution of multiple tasks with result aggregation.
Useful for fan-out operations like multi-query retrieval.

Pattern: Split -> [Task1, Task2, ...] (parallel) -> Aggregate -> Result
"""


import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from app.rag.core.hashing import stable_hash
from app.rag.core.logging import get_logger
from app.rag.workflows.base import (
    BaseWorkflow,
    WorkflowMode,
    WorkflowResult,
)

logger = get_logger("rag.workflows.parallelization")


class ParallelTask:
    """A task that can be executed in parallel."""

    def __init__(
        self,
        name: str,
        func: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]],
        weight: float = 1.0,
    ):
        self.name = name
        self.func = func
        self.weight = weight

    async def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        """Execute the task."""
        return await self.func(state)


class ParallelWorkflow(BaseWorkflow):
    """
    Parallel workflow executes multiple tasks concurrently.

    All tasks receive the same input state and their results
    are aggregated using a configurable aggregation function.

    Usage:
        workflow = ParallelWorkflow(aggregator=my_aggregator)
        workflow.add_task("vector_search", vector_func)
        workflow.add_task("keyword_search", keyword_func)
        result = await workflow.run({"question": "..."})
    """

    def __init__(
        self,
        aggregator: Callable[[list[dict[str, Any]]], Awaitable[dict[str, Any]]] | None = None,
        fail_fast: bool = False,
        max_concurrency: int | None = None,
        **kwargs,
    ):
        """
        Initialize the parallel workflow.

        Args:
            aggregator: Function to aggregate results
            fail_fast: Stop all tasks if one fails
            max_concurrency: Maximum concurrent tasks (None = unlimited)
            **kwargs: Additional configuration
        """
        super().__init__(**kwargs)
        self._tasks: list[ParallelTask] = []
        self._aggregator = aggregator or self._default_aggregator
        self.fail_fast = fail_fast
        self.max_concurrency = max_concurrency

    @property
    def mode(self) -> WorkflowMode:
        return WorkflowMode.PARALLEL

    def add_task(
        self,
        name: str,
        func: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]],
        weight: float = 1.0,
    ) -> "ParallelWorkflow":
        """
        Add a parallel task.

        Args:
            name: Task name
            func: Async function
            weight: Task weight for aggregation

        Returns:
            Self for chaining
        """
        self._tasks.append(ParallelTask(name, func, weight))
        return self

    def set_aggregator(
        self,
        aggregator: Callable[[list[dict[str, Any]]], Awaitable[dict[str, Any]]],
    ) -> "ParallelWorkflow":
        """Set the result aggregator."""
        self._aggregator = aggregator
        return self

    async def _execute_task(
        self,
        task: ParallelTask,
        state: dict[str, Any],
        semaphore: asyncio.Semaphore | None,
    ) -> dict[str, Any]:
        """Execute a single task with optional semaphore."""
        if semaphore:
            async with semaphore:
                return await task.execute(state)
        return await task.execute(state)

    def _validation_result(self, state: dict[str, Any]) -> WorkflowResult | None:
        if not self.validate_state(state):
            return self.create_result(
                state,
                success=False,
                error="Invalid state: missing question/query",
            )
        if self._tasks:
            return None
        return self.create_result(
            state,
            success=False,
            error="No tasks configured",
        )

    def _task_semaphore(self) -> asyncio.Semaphore | None:
        if self.max_concurrency:
            return asyncio.Semaphore(self.max_concurrency)
        return None

    async def _collect_task_results(
        self,
        state: dict[str, Any],
        *,
        semaphore: asyncio.Semaphore | None,
    ) -> tuple[list[dict[str, Any]], list[str], list[str]]:
        task_coroutines = [self._execute_task(task, dict(state), semaphore) for task in self._tasks]
        results: list[dict[str, Any]] = []
        errors: list[str] = []
        completed_tasks: list[str] = []
        if self.fail_fast:
            results = await asyncio.gather(*task_coroutines)
            completed_tasks = [task.name for task in self._tasks]
            return results, errors, completed_tasks

        task_results = await asyncio.gather(*task_coroutines, return_exceptions=True)
        for task, result in zip(self._tasks, task_results, strict=False):
            if isinstance(result, Exception):
                errors.append(f"{task.name}: {str(result)}")
                logger.error("Task %s failed: %s", task.name, result)
                continue
            results.append(result)
            completed_tasks.append(task.name)
        return results, errors, completed_tasks

    async def _aggregate_results(
        self,
        *,
        state: dict[str, Any],
        results: list[dict[str, Any]],
        errors: list[str],
        completed_tasks: list[str],
        execution_path: list[str],
    ) -> WorkflowResult:
        aggregated_state = await self._aggregator(results)
        for key, value in state.items():
            if key not in aggregated_state:
                aggregated_state[key] = value
        aggregated_state["parallel_tasks"] = completed_tasks
        if errors:
            aggregated_state["parallel_errors"] = errors
        success = len(results) > 0
        error_msg = "; ".join(errors) if errors and not results else None
        return self.create_result(
            aggregated_state,
            success=success,
            error=error_msg,
            execution_path=execution_path,
            metadata={"tasks_completed": len(results), "tasks_failed": len(errors)},
        )

    async def run(self, state: dict[str, Any]) -> WorkflowResult:
        """
        Execute the parallel workflow.

        Args:
            state: Initial state

        Returns:
            WorkflowResult with aggregated state
        """
        validation_result = self._validation_result(state)
        if validation_result is not None:
            return validation_result
        execution_path: list[str] = ["parallel_start"]
        semaphore = self._task_semaphore()
        try:
            results, errors, completed_tasks = await self._collect_task_results(state, semaphore=semaphore)
        except Exception as e:
            logger.exception("Parallel execution failed: %s", e)
            return self.create_result(
                state,
                success=False,
                error=str(e),
                execution_path=execution_path,
            )

        execution_path.extend(completed_tasks)
        execution_path.append("aggregate")

        # Aggregate results
        try:
            return await self._aggregate_results(
                state=state,
                results=results,
                errors=errors,
                completed_tasks=completed_tasks,
                execution_path=execution_path,
            )
        except Exception as e:
            logger.exception("Aggregation failed: %s", e)
            return self.create_result(
                state,
                success=False,
                error=f"Aggregation failed: {e}",
                execution_path=execution_path,
            )

    async def _default_aggregator(self, results: list[dict[str, Any]]) -> dict[str, Any]:
        """
        Default aggregation: merge all results.

        Later results override earlier ones for same keys.
        Lists are concatenated. Contexts are combined.
        """
        if not results:
            return {}
        await asyncio.sleep(0)

        merged: dict[str, Any] = {}
        all_contexts: list[Any] = []

        for result in results:
            for key, value in result.items():
                if key == "contexts" and isinstance(value, list):
                    all_contexts.extend(value)
                elif key in merged and isinstance(merged[key], list) and isinstance(value, list):
                    merged[key].extend(value)
                else:
                    merged[key] = value

        if all_contexts:
            merged["contexts"] = all_contexts

        return merged


def create_multi_query_aggregator() -> Callable[[list[dict[str, Any]]], Awaitable[dict[str, Any]]]:
    """
    Create an aggregator for multi-query retrieval.

    Deduplicates and ranks contexts from multiple queries.
    """
    async def aggregator(results: list[dict[str, Any]]) -> dict[str, Any]:
        await asyncio.sleep(0)
        all_contexts = []
        seen_ids = set()

        for result in results:
            contexts = result.get("contexts", [])
            for ctx in contexts:
                ctx_id = ctx.get("chunk_id") or ctx.get("id") or f"content:{stable_hash(str(ctx.get('content') or ''))}"
                if ctx_id not in seen_ids:
                    seen_ids.add(ctx_id)
                    all_contexts.append(ctx)

        # Sort by score if available
        all_contexts.sort(
            key=lambda x: x.get("score", 0) or 0,
            reverse=True,
        )

        # Take first result's answer if available
        answer = ""
        for result in results:
            if result.get("answer"):
                answer = result["answer"]
                break

        return {
            "contexts": all_contexts,
            "answer": answer,
            "multi_query_count": len(results),
        }

    return aggregator
