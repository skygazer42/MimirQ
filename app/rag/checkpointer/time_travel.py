"""
Time travel debugging module for LangGraph workflows.

Provides the following capabilities:
- List checkpoint history
- Replay execution from a specific checkpoint
- Fork execution with modified state
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from langgraph.graph.state import CompiledStateGraph

from app.rag.core.logging import get_logger

logger = get_logger("rag.checkpointer.time_travel")


@dataclass
class CheckpointInfo:
    """Information about a checkpoint."""

    checkpoint_id: str
    thread_id: str
    parent_checkpoint_id: str | None
    created_at: datetime | None

    # State information
    values: dict[str, Any]
    next_nodes: list[str]

    # Metadata
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "checkpoint_id": self.checkpoint_id,
            "thread_id": self.thread_id,
            "parent_checkpoint_id": self.parent_checkpoint_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "values": self.values,
            "next_nodes": self.next_nodes,
            "metadata": self.metadata,
        }


@dataclass
class ForkResult:
    """Result of a fork operation."""

    new_checkpoint_id: str
    thread_id: str
    original_checkpoint_id: str
    updates_applied: dict[str, Any]
    config: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "new_checkpoint_id": self.new_checkpoint_id,
            "thread_id": self.thread_id,
            "original_checkpoint_id": self.original_checkpoint_id,
            "updates_applied": self.updates_applied,
        }


class TimeTravel:
    """
    Time Travel interface for LangGraph workflows.

    Wraps a compiled graph and provides debugging capabilities:
    - View checkpoint history
    - Replay from any checkpoint
    - Fork and modify state
    """

    def __init__(self, graph: CompiledStateGraph):
        """
        Initialize TimeTravel with a compiled graph.

        Args:
            graph: Compiled LangGraph state graph
        """
        self.graph = graph

        if graph.checkpointer is None:
            raise ValueError(
                "Graph must have a checkpointer to use time travel. "
                "Compile with: graph.compile(checkpointer=...)"
            )

    def get_history(
        self,
        thread_id: str,
        *,
        limit: int | None = None,
        before: str | None = None,
    ) -> list[CheckpointInfo]:
        """
        Get checkpoint history for a thread.

        Args:
            thread_id: Thread ID to get history for
            limit: Maximum number of checkpoints to return
            before: Only return checkpoints before this checkpoint_id

        Returns:
            List of CheckpointInfo objects, newest first
        """
        config = {"configurable": {"thread_id": thread_id}}

        if before:
            config["configurable"]["checkpoint_id"] = before

        history: list[CheckpointInfo] = []

        try:
            states = self.graph.get_state_history(config, limit=limit)

            for state in states:
                checkpoint_id = state.config.get("configurable", {}).get("checkpoint_id")
                parent_id = state.parent_config.get("configurable", {}).get("checkpoint_id") if state.parent_config else None

                # Extract timestamp from metadata if available
                created_at = None
                if state.metadata and "created_at" in state.metadata:
                    try:
                        created_at = datetime.fromisoformat(state.metadata["created_at"])
                    except (ValueError, TypeError) as exc:
                        logger.debug("Ignoring non-critical time-travel fallback failure: %s", exc)

                info = CheckpointInfo(
                    checkpoint_id=checkpoint_id or "",
                    thread_id=thread_id,
                    parent_checkpoint_id=parent_id,
                    created_at=created_at,
                    values=dict(state.values) if state.values else {},
                    next_nodes=list(state.next) if state.next else [],
                    metadata=dict(state.metadata) if state.metadata else {},
                )
                history.append(info)

        except Exception as e:
            logger.warning("Failed to get state history for thread %s: %s", thread_id, e)

        return history

    def get_checkpoint(
        self,
        thread_id: str,
        checkpoint_id: str,
    ) -> CheckpointInfo | None:
        """
        Get a specific checkpoint.

        Args:
            thread_id: Thread ID
            checkpoint_id: Checkpoint ID

        Returns:
            CheckpointInfo or None if not found
        """
        config = {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_id": checkpoint_id,
            }
        }

        try:
            state = self.graph.get_state(config)
            if state is None:
                return None

            parent_id = state.parent_config.get("configurable", {}).get("checkpoint_id") if state.parent_config else None

            created_at = None
            if state.metadata and "created_at" in state.metadata:
                try:
                    created_at = datetime.fromisoformat(state.metadata["created_at"])
                except (ValueError, TypeError) as exc:
                    logger.debug("Ignoring non-critical time-travel fallback failure: %s", exc)

            return CheckpointInfo(
                checkpoint_id=checkpoint_id,
                thread_id=thread_id,
                parent_checkpoint_id=parent_id,
                created_at=created_at,
                values=dict(state.values) if state.values else {},
                next_nodes=list(state.next) if state.next else [],
                metadata=dict(state.metadata) if state.metadata else {},
            )

        except Exception as e:
            logger.warning("Failed to get checkpoint %s: %s", checkpoint_id, e)
            return None

    def replay(
        self,
        thread_id: str,
        checkpoint_id: str,
        *,
        stream_mode: str | None = None,
    ) -> dict[str, Any]:
        """
        Replay execution from a specific checkpoint.

        Note: Replay does not re-execute already completed nodes.
        It continues from the checkpoint's "next" nodes.

        Args:
            thread_id: Thread ID
            checkpoint_id: Checkpoint ID to replay from
            stream_mode: Optional stream mode ("updates", "values")

        Returns:
            Final state after replay
        """
        config = {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_id": checkpoint_id,
            }
        }

        logger.info(
            "Replaying from checkpoint %s on thread %s",
            checkpoint_id, thread_id
        )

        if stream_mode:
            result = None
            for step in self.graph.stream(None, config, stream_mode=stream_mode):
                result = step
            return result or {}
        else:
            return self.graph.invoke(None, config)

    def fork(
        self,
        thread_id: str,
        checkpoint_id: str,
        updates: dict[str, Any],
        *,
        continue_execution: bool = True,
        stream_mode: str | None = None,
    ) -> ForkResult | dict[str, Any]:
        """
        Fork from a checkpoint with modified state.

        Creates a new checkpoint with the updated values,
        then optionally continues execution from there.

        Args:
            thread_id: Thread ID
            checkpoint_id: Checkpoint ID to fork from
            updates: State updates to apply
            continue_execution: Whether to continue execution after fork
            stream_mode: Optional stream mode for execution

        Returns:
            If continue_execution=True: Final execution state
            If continue_execution=False: ForkResult with new checkpoint info
        """
        original_config = {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_id": checkpoint_id,
            }
        }

        logger.info(
            "Forking from checkpoint %s with updates: %s",
            checkpoint_id, list(updates.keys())
        )

        # Create new checkpoint with updated state
        new_config = self.graph.update_state(original_config, values=updates)

        new_checkpoint_id = new_config.get("configurable", {}).get("checkpoint_id", "")

        if not continue_execution:
            return ForkResult(
                new_checkpoint_id=new_checkpoint_id,
                thread_id=thread_id,
                original_checkpoint_id=checkpoint_id,
                updates_applied=updates,
                config=new_config,
            )

        # Continue execution from the forked checkpoint
        if stream_mode:
            result = None
            for step in self.graph.stream(None, new_config, stream_mode=stream_mode):
                result = step
            return result or {}
        else:
            return self.graph.invoke(None, new_config)

    def compare_checkpoints(
        self,
        thread_id: str,
        checkpoint_id_a: str,
        checkpoint_id_b: str,
    ) -> dict[str, Any]:
        """
        Compare two checkpoints and return differences.

        Args:
            thread_id: Thread ID
            checkpoint_id_a: First checkpoint ID
            checkpoint_id_b: Second checkpoint ID

        Returns:
            Dictionary with differences
        """
        cp_a = self.get_checkpoint(thread_id, checkpoint_id_a)
        cp_b = self.get_checkpoint(thread_id, checkpoint_id_b)

        if cp_a is None or cp_b is None:
            return {
                "error": "One or both checkpoints not found",
                "found_a": cp_a is not None,
                "found_b": cp_b is not None,
            }

        # Find keys that differ
        all_keys = set(cp_a.values.keys()) | set(cp_b.values.keys())

        added = {}  # In B but not A
        removed = {}  # In A but not B
        modified = {}  # Different values

        for key in all_keys:
            in_a = key in cp_a.values
            in_b = key in cp_b.values

            if in_b and not in_a:
                added[key] = cp_b.values[key]
            elif in_a and not in_b:
                removed[key] = cp_a.values[key]
            elif cp_a.values[key] != cp_b.values[key]:
                modified[key] = {
                    "old": cp_a.values[key],
                    "new": cp_b.values[key],
                }

        return {
            "checkpoint_a": checkpoint_id_a,
            "checkpoint_b": checkpoint_id_b,
            "added_keys": added,
            "removed_keys": removed,
            "modified_keys": modified,
            "next_nodes_a": cp_a.next_nodes,
            "next_nodes_b": cp_b.next_nodes,
        }

    def get_execution_path(
        self,
        thread_id: str,
        checkpoint_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Get the execution path (sequence of nodes executed) for a thread.

        Args:
            thread_id: Thread ID
            checkpoint_id: Optional checkpoint ID (defaults to latest)

        Returns:
            List of execution steps with node info
        """
        history = self.get_history(thread_id)

        if not history:
            return []

        # If checkpoint_id specified, filter history
        if checkpoint_id:
            filtered = []
            found = False
            for cp in history:
                filtered.append(cp)
                if cp.checkpoint_id == checkpoint_id:
                    found = True
                    break
            if found:
                history = filtered

        # Reverse to get chronological order
        history = list(reversed(history))

        path = []
        for i, cp in enumerate(history):
            step = {
                "step": i,
                "checkpoint_id": cp.checkpoint_id,
                "next_nodes": cp.next_nodes,
                "state_keys": list(cp.values.keys()),
            }
            path.append(step)

        return path


# Global TimeTravel instance cache
_time_travel_instances: dict[int, TimeTravel] = {}


def get_time_travel(graph: CompiledStateGraph) -> TimeTravel:
    """
    Get or create a TimeTravel instance for a graph.

    Args:
        graph: Compiled LangGraph state graph

    Returns:
        TimeTravel instance
    """
    graph_id = id(graph)

    if graph_id not in _time_travel_instances:
        _time_travel_instances[graph_id] = TimeTravel(graph)

    return _time_travel_instances[graph_id]


def clear_time_travel_cache() -> None:
    """Clear the TimeTravel instance cache."""
    global _time_travel_instances
    _time_travel_instances = {}
