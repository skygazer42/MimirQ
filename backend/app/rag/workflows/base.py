"""
Base workflow interface and common types.

Defines the abstract base class for all workflow patterns
and the WorkflowMode enumeration.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict, Callable, Awaitable
from dataclasses import dataclass, field


class WorkflowMode(str, Enum):
    """Available workflow modes."""
    CHAIN = "chain"
    ROUTING = "routing"
    PARALLEL = "parallel"
    REACT = "react"
    PLANNER = "planner"
    EVALUATOR = "evaluator"


class WorkflowState(TypedDict, total=False):
    """Standard workflow state structure."""
    question: str
    query: str
    history: List[Dict[str, str]]
    context: str
    contexts: List[Dict[str, Any]]
    answer: str
    citations: List[Dict[str, Any]]
    metadata: Dict[str, Any]
    error: Optional[str]
    # Workflow-specific fields
    route: Optional[str]
    plan: Optional[List[str]]
    current_step: int
    iterations: int
    score: float
    reasoning_trace: List[str]


@dataclass
class WorkflowResult:
    """Result of a workflow execution."""
    success: bool
    state: Dict[str, Any]
    answer: str = ""
    error: Optional[str] = None
    iterations: int = 0
    execution_path: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class BaseWorkflow(ABC):
    """
    Abstract base class for workflow patterns.

    All workflow implementations must inherit from this class
    and implement the run() method.

    Attributes:
        name: Workflow name for logging/tracing
        mode: WorkflowMode enumeration value
        max_iterations: Maximum iterations for iterative workflows
        timeout_sec: Execution timeout in seconds
    """

    def __init__(
        self,
        name: Optional[str] = None,
        max_iterations: int = 10,
        timeout_sec: int = 120,
        **kwargs,
    ):
        """
        Initialize the workflow.

        Args:
            name: Optional workflow name
            max_iterations: Maximum iterations
            timeout_sec: Execution timeout
            **kwargs: Additional configuration
        """
        self.name = name or self.__class__.__name__
        self.max_iterations = max_iterations
        self.timeout_sec = timeout_sec
        self._config = kwargs

    @property
    @abstractmethod
    def mode(self) -> WorkflowMode:
        """Return the workflow mode."""
        pass

    @abstractmethod
    async def run(self, state: Dict[str, Any]) -> WorkflowResult:
        """
        Execute the workflow.

        Args:
            state: Initial state dictionary

        Returns:
            WorkflowResult with final state and metadata
        """
        pass

    def validate_state(self, state: Dict[str, Any]) -> bool:
        """
        Validate that state has required fields.

        Args:
            state: State to validate

        Returns:
            True if valid
        """
        return "question" in state or "query" in state

    def get_question(self, state: Dict[str, Any]) -> str:
        """Extract question from state."""
        return state.get("question") or state.get("query") or ""

    def create_result(
        self,
        state: Dict[str, Any],
        success: bool = True,
        error: Optional[str] = None,
        **kwargs,
    ) -> WorkflowResult:
        """
        Create a WorkflowResult from state.

        Args:
            state: Final state
            success: Whether workflow succeeded
            error: Optional error message
            **kwargs: Additional result fields

        Returns:
            WorkflowResult
        """
        return WorkflowResult(
            success=success,
            state=state,
            answer=state.get("answer", ""),
            error=error,
            iterations=kwargs.get("iterations", 0),
            execution_path=kwargs.get("execution_path", []),
            metadata=kwargs.get("metadata", {}),
        )


class WorkflowStep:
    """
    Represents a single step in a workflow.

    Wraps a function that transforms state.
    """

    def __init__(
        self,
        name: str,
        func: Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]],
        condition: Optional[Callable[[Dict[str, Any]], bool]] = None,
    ):
        """
        Initialize a workflow step.

        Args:
            name: Step name
            func: Async function that transforms state
            condition: Optional condition to check before executing
        """
        self.name = name
        self.func = func
        self.condition = condition

    async def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the step."""
        if self.condition and not self.condition(state):
            return state
        return await self.func(state)

    def should_execute(self, state: Dict[str, Any]) -> bool:
        """Check if step should execute."""
        if self.condition is None:
            return True
        return self.condition(state)
