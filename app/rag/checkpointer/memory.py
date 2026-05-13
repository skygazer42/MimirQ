"""
In-memory checkpoint saver (for workflow state).

Non-persistent checkpoints suitable for development and testing environments.
Data is lost after application restart.
"""

import builtins
import threading
from collections import defaultdict
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from app.rag.core.logging import get_logger

logger = get_logger("rag.checkpointer.memory")


class MemorySaver:
    """
    In-memory checkpoint saver.

    Stores checkpoints in memory. Fast but non-persistent.
    Thread-safe implementation.
    """

    def __init__(self):
        """Initialize the memory saver."""
        self._storage: dict[str, dict[str, Any]] = {}
        self._by_thread: dict[str, list[str]] = defaultdict(list)
        self._lock = threading.RLock()

    def put(
        self,
        config: dict[str, Any],
        checkpoint: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Save a checkpoint.

        Args:
            config: Configuration with thread_id
            checkpoint: Checkpoint state to save
            metadata: Optional metadata

        Returns:
            Updated config with checkpoint_id
        """
        with self._lock:
            thread_id = config.get("configurable", {}).get("thread_id", str(uuid4()))
            parent_id = config.get("configurable", {}).get("checkpoint_id")
            checkpoint_id = str(uuid4())

            self._storage[checkpoint_id] = {
                "id": checkpoint_id,
                "thread_id": thread_id,
                "parent_id": parent_id,
                "checkpoint": checkpoint,
                "metadata": metadata or {},
                "created_at": datetime.now(UTC).replace(tzinfo=None).isoformat(),
            }

            self._by_thread[thread_id].append(checkpoint_id)

            return {
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_id": checkpoint_id,
                }
            }

    def get(self, config: dict[str, Any]) -> dict[str, Any] | None:
        """
        Get a checkpoint.

        Args:
            config: Configuration with thread_id and optional checkpoint_id

        Returns:
            Checkpoint state or None
        """
        with self._lock:
            thread_id = config.get("configurable", {}).get("thread_id")
            checkpoint_id = config.get("configurable", {}).get("checkpoint_id")

            if checkpoint_id and checkpoint_id in self._storage:
                return self._storage[checkpoint_id]["checkpoint"]

            if thread_id and thread_id in self._by_thread:
                ids = self._by_thread[thread_id]
                if ids:
                    return self._storage[ids[-1]]["checkpoint"]

            return None

    def get_tuple(self, config: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]] | None:
        """
        Get checkpoint with metadata.

        Args:
            config: Configuration

        Returns:
            Tuple of (checkpoint, config) or None
        """
        with self._lock:
            thread_id = config.get("configurable", {}).get("thread_id")
            checkpoint_id = config.get("configurable", {}).get("checkpoint_id")

            data = None

            if checkpoint_id and checkpoint_id in self._storage:
                data = self._storage[checkpoint_id]
            elif thread_id and thread_id in self._by_thread:
                ids = self._by_thread[thread_id]
                if ids:
                    data = self._storage[ids[-1]]

            if data is None:
                return None

            return data["checkpoint"], {
                "configurable": {
                    "thread_id": data["thread_id"],
                    "checkpoint_id": data["id"],
                }
            }

    def list(
        self,
        config: dict[str, Any],
        limit: int = 100,
        before: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        List checkpoints for a thread.

        Args:
            config: Configuration with thread_id
            limit: Maximum checkpoints
            before: Return checkpoints before this ID

        Returns:
            List of checkpoint data
        """
        with self._lock:
            thread_id = config.get("configurable", {}).get("thread_id")
            if not thread_id or thread_id not in self._by_thread:
                return []

            ids = self._by_thread[thread_id]

            if before and before in ids:
                idx = ids.index(before)
                ids = ids[:idx]

            # Return in reverse order (newest first)
            ids = list(reversed(ids))[:limit]

            return [self._storage[cid] for cid in ids if cid in self._storage]

    def delete(self, config: dict[str, Any]) -> bool:
        """
        Delete a checkpoint.

        Args:
            config: Configuration with checkpoint_id

        Returns:
            True if deleted
        """
        with self._lock:
            checkpoint_id = config.get("configurable", {}).get("checkpoint_id")
            if not checkpoint_id or checkpoint_id not in self._storage:
                return False

            data = self._storage.pop(checkpoint_id)
            thread_id = data["thread_id"]

            if thread_id in self._by_thread:
                try:
                    self._by_thread[thread_id].remove(checkpoint_id)
                except ValueError:
                    pass

            return True

    def clear_thread(self, thread_id: str) -> int:
        """
        Clear all checkpoints for a thread.

        Args:
            thread_id: Thread ID

        Returns:
            Number of checkpoints deleted
        """
        with self._lock:
            if thread_id not in self._by_thread:
                return 0

            ids = self._by_thread.pop(thread_id)
            for cid in ids:
                self._storage.pop(cid, None)

            return len(ids)

    def clear_all(self) -> int:
        """
        Clear all checkpoints.

        Returns:
            Number of checkpoints deleted
        """
        with self._lock:
            count = len(self._storage)
            self._storage.clear()
            self._by_thread.clear()
            return count

    def get_thread_ids(self, limit: int = 100) -> builtins.list[str]:
        """
        Get all unique thread IDs.

        Args:
            limit: Maximum threads

        Returns:
            List of thread IDs
        """
        with self._lock:
            return list(self._by_thread.keys())[:limit]
