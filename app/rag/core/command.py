"""
Command object for decoupling state updates from flow control.

Provides a unified way to specify both state mutations and
routing decisions in workflow nodes.

Usage:
    @task
    def my_node(state: Dict[str, Any]) -> Command:
        # Process...
        return Command(
            update={"answer": "result"},
            goto="next_node",
        )
"""


from dataclasses import dataclass, field
from typing import Any


@dataclass
class Command:
    """
    Command object for workflow node returns.

    Encapsulates both state updates and flow control decisions,
    allowing nodes to be more declarative and easier to compose.

    Attributes:
        update: State updates to apply
        goto: Next node(s) to route to
        resume: Value to resume interrupted workflow with
        send: Messages to send to specific nodes
        metadata: Additional metadata for tracing/debugging

    Examples:
        # Simple state update
        Command(update={"answer": "Hello"})

        # State update with routing
        Command(update={"score": 0.8}, goto="evaluate")

        # Conditional routing
        Command(goto="retry" if score < 0.7 else "finish")

        # Multiple destinations (fan-out)
        Command(goto=["search_a", "search_b"])

        # Resume from interrupt
        Command(resume=user_input)

        # Send to specific nodes
        Command(send=[
            Send("worker_1", {"task": "process chunk 1"}),
            Send("worker_2", {"task": "process chunk 2"}),
        ])
    """

    update: dict[str, Any] = field(default_factory=dict)
    goto: str | list[str] | None = None
    resume: Any | None = None
    send: list["Send"] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Validate command configuration."""
        if self.resume is not None and (self.goto or self.update):
            # Resume is a special case - shouldn't combine with regular flow
            pass  # Allow for flexibility, but log warning in actual use

    @classmethod
    def continue_to(cls, node: str, **updates) -> "Command":
        """Create a command that continues to a specific node."""
        return cls(update=updates, goto=node)

    @classmethod
    def finish(cls, **updates) -> "Command":
        """Create a command that finishes the workflow."""
        return cls(update=updates, goto="__end__")

    @classmethod
    def retry(cls, **updates) -> "Command":
        """Create a command that retries the current node."""
        return cls(update=updates, goto="__retry__")

    @classmethod
    def fan_out(cls, nodes: list[str], **updates) -> "Command":
        """Create a command that fans out to multiple nodes."""
        return cls(update=updates, goto=nodes)

    @classmethod
    def resume_with(cls, value: Any) -> "Command":
        """Create a command that resumes an interrupted workflow."""
        return cls(resume=value)

    def with_update(self, **updates) -> "Command":
        """Return a new Command with additional updates."""
        merged = {**self.update, **updates}
        return Command(
            update=merged,
            goto=self.goto,
            resume=self.resume,
            send=self.send,
            metadata=self.metadata,
        )

    def with_metadata(self, **meta) -> "Command":
        """Return a new Command with additional metadata."""
        merged = {**self.metadata, **meta}
        return Command(
            update=self.update,
            goto=self.goto,
            resume=self.resume,
            send=self.send,
            metadata=merged,
        )

    def is_terminal(self) -> bool:
        """Check if this command ends the workflow."""
        return self.goto == "__end__"

    def is_retry(self) -> bool:
        """Check if this command is a retry."""
        return self.goto == "__retry__"

    def is_fan_out(self) -> bool:
        """Check if this command fans out to multiple nodes."""
        return isinstance(self.goto, list) and len(self.goto) > 1

    def get_destinations(self) -> list[str]:
        """Get list of destination nodes."""
        if self.goto is None:
            return []
        if isinstance(self.goto, str):
            return [self.goto]
        return list(self.goto)


@dataclass
class Send:
    """
    Send a message to a specific node.

    Used for dynamic fan-out where different data goes to different nodes.
    """

    node: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {"node": self.node, "data": self.data}


@dataclass
class Interrupt:
    """
    Interrupt value for human-in-the-loop workflows.

    When a node returns an Interrupt, the workflow pauses
    and waits for external input via Command(resume=...).
    """

    value: Any
    prompt: str = ""
    options: list[str] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "value": self.value,
            "prompt": self.prompt,
            "options": self.options,
            "metadata": self.metadata,
        }


def interrupt(
    value: Any = None,
    prompt: str = "",
    options: list[str] | None = None,
    **metadata,
) -> Interrupt:
    """
    Create an interrupt to pause workflow execution.

    This function is used in nodes that require human review
    or external input before continuing.

    Args:
        value: Value to pass to the interrupt handler
        prompt: Human-readable prompt explaining what's needed
        options: Optional list of valid response options
        **metadata: Additional metadata

    Returns:
        Interrupt object

    Example:
        @task
        def review_answer(state: Dict[str, Any]) -> Command | Interrupt:
            if state.get("requires_review"):
                return interrupt(
                    value={"answer": state["answer"]},
                    prompt="Please review this answer",
                    options=["approve", "reject", "edit"],
                )
            return Command(goto="finish")
    """
    return Interrupt(
        value=value,
        prompt=prompt,
        options=options,
        metadata=metadata,
    )


class CommandProcessor:
    """
    Processes Command objects and applies them to workflow state.

    Used internally by workflow engines to interpret Command returns.
    """

    def __init__(self, state: dict[str, Any]):
        """Initialize with current state."""
        self.state = dict(state)
        self.pending_sends: list[Send] = []
        self.next_nodes: list[str] = []
        self.is_interrupted: bool = False
        self.interrupt_value: Interrupt | None = None

    def process(self, result: Command | Interrupt | dict[str, Any]) -> dict[str, Any]:
        """
        Process a node result and update state.

        Args:
            result: Node return value

        Returns:
            Updated state dictionary
        """
        if isinstance(result, Interrupt):
            self.is_interrupted = True
            self.interrupt_value = result
            return self.state

        if isinstance(result, Command):
            # Apply state updates
            if result.update:
                self.state.update(result.update)

            # Process routing
            if result.goto:
                self.next_nodes = result.get_destinations()

            # Process sends
            if result.send:
                self.pending_sends.extend(result.send)

            # Add command metadata to state
            if result.metadata:
                meta = self.state.get("_command_metadata", {})
                meta.update(result.metadata)
                self.state["_command_metadata"] = meta

            return self.state

        if isinstance(result, dict):
            # Plain dict - just update state
            self.state.update(result)
            return self.state

        # Unknown type - return unchanged
        return self.state

    def get_next_nodes(self) -> list[str]:
        """Get the next nodes to execute."""
        return self.next_nodes

    def get_pending_sends(self) -> list[Send]:
        """Get pending Send operations."""
        return self.pending_sends

    def should_interrupt(self) -> bool:
        """Check if workflow should be interrupted."""
        return self.is_interrupted

    def get_interrupt(self) -> Interrupt | None:
        """Get the interrupt value if any."""
        return self.interrupt_value


# Type aliases for cleaner signatures
NodeReturn = Command | Interrupt | dict[str, Any]
