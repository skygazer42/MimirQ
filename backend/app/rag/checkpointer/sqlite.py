"""
SQLite-based checkpoint saver for workflow state persistence.

Provides persistent storage for workflow checkpoints,
enabling session recovery and history queries.

Usage:
    from app.rag.checkpointer import SqliteSaver

    saver = SqliteSaver("./data/checkpoints.db")
    workflow = create_workflow(checkpointer=saver)
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple
from uuid import uuid4

from app.core.config import settings

logger = logging.getLogger(__name__)

# Configuration
CHECKPOINT_SQLITE_PATH = getattr(settings, "CHECKPOINT_SQLITE_PATH", "./data/checkpoints.db")


class CheckpointData:
    """
    Represents a workflow checkpoint.

    Attributes:
        id: Checkpoint ID
        thread_id: Workflow thread ID
        parent_id: Parent checkpoint ID (for branching)
        checkpoint: Serialized checkpoint state
        metadata: Additional metadata
        created_at: Creation timestamp
    """

    def __init__(
        self,
        id: str,
        thread_id: str,
        parent_id: Optional[str],
        checkpoint: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
        created_at: Optional[datetime] = None,
    ):
        self.id = id
        self.thread_id = thread_id
        self.parent_id = parent_id
        self.checkpoint = checkpoint
        self.metadata = metadata or {}
        self.created_at = created_at or datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "thread_id": self.thread_id,
            "parent_id": self.parent_id,
            "checkpoint": self.checkpoint,
            "metadata": self.metadata,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CheckpointData":
        """Create from dictionary."""
        created_at = data.get("created_at")
        if isinstance(created_at, str):
            created_at = datetime.fromisoformat(created_at)

        return cls(
            id=data["id"],
            thread_id=data["thread_id"],
            parent_id=data.get("parent_id"),
            checkpoint=data.get("checkpoint", {}),
            metadata=data.get("metadata"),
            created_at=created_at,
        )


class SqliteSaver:
    """
    SQLite-based checkpoint saver.

    Provides persistent storage for workflow checkpoints with
    support for session recovery and history queries.

    Thread-safe implementation using thread-local connections.
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        table_name: str = "checkpoints",
    ):
        """
        Initialize the SQLite saver.

        Args:
            db_path: Path to SQLite database file
            table_name: Name of the checkpoints table
        """
        self.db_path = db_path or CHECKPOINT_SQLITE_PATH
        self.table_name = table_name
        self._local = threading.local()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        """Get thread-local database connection."""
        if not hasattr(self._local, 'conn') or self._local.conn is None:
            # Ensure directory exists
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)

            self._local.conn = sqlite3.connect(
                self.db_path,
                check_same_thread=False,
                isolation_level=None,  # Autocommit mode
            )
            self._local.conn.row_factory = sqlite3.Row

        return self._local.conn

    @contextmanager
    def _cursor(self) -> Iterator[sqlite3.Cursor]:
        """Get a cursor with automatic commit/rollback."""
        conn = self._get_conn()
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()

    def _init_db(self) -> None:
        """Initialize database schema."""
        conn = self._get_conn()

        conn.execute(f"""
            CREATE TABLE IF NOT EXISTS {self.table_name} (
                id TEXT PRIMARY KEY,
                thread_id TEXT NOT NULL,
                parent_id TEXT,
                checkpoint TEXT NOT NULL,
                metadata TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (parent_id) REFERENCES {self.table_name}(id)
            )
        """)

        conn.execute(f"""
            CREATE INDEX IF NOT EXISTS idx_{self.table_name}_thread
            ON {self.table_name}(thread_id)
        """)

        conn.execute(f"""
            CREATE INDEX IF NOT EXISTS idx_{self.table_name}_parent
            ON {self.table_name}(parent_id)
        """)

        conn.execute(f"""
            CREATE INDEX IF NOT EXISTS idx_{self.table_name}_created
            ON {self.table_name}(created_at)
        """)

        logger.debug("Initialized SQLite checkpoint database: %s", self.db_path)

    def put(
        self,
        config: Dict[str, Any],
        checkpoint: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Save a checkpoint.

        Args:
            config: Configuration with thread_id and optional checkpoint_id
            checkpoint: Checkpoint state to save
            metadata: Optional metadata

        Returns:
            Updated config with new checkpoint_id
        """
        thread_id = config.get("configurable", {}).get("thread_id", str(uuid4()))
        parent_id = config.get("configurable", {}).get("checkpoint_id")
        checkpoint_id = str(uuid4())

        data = CheckpointData(
            id=checkpoint_id,
            thread_id=thread_id,
            parent_id=parent_id,
            checkpoint=checkpoint,
            metadata=metadata,
        )

        conn = self._get_conn()
        conn.execute(f"""
            INSERT INTO {self.table_name}
            (id, thread_id, parent_id, checkpoint, metadata, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            data.id,
            data.thread_id,
            data.parent_id,
            json.dumps(data.checkpoint, ensure_ascii=False),
            json.dumps(data.metadata, ensure_ascii=False) if data.metadata else None,
            data.created_at.isoformat(),
        ))

        logger.debug("Saved checkpoint %s for thread %s", checkpoint_id, thread_id)

        # Return updated config
        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_id": checkpoint_id,
            }
        }

    def get(self, config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Get a checkpoint.

        Args:
            config: Configuration with thread_id and optional checkpoint_id

        Returns:
            Checkpoint state or None
        """
        thread_id = config.get("configurable", {}).get("thread_id")
        checkpoint_id = config.get("configurable", {}).get("checkpoint_id")

        if not thread_id:
            return None

        conn = self._get_conn()

        if checkpoint_id:
            # Get specific checkpoint
            cursor = conn.execute(f"""
                SELECT * FROM {self.table_name}
                WHERE id = ? AND thread_id = ?
            """, (checkpoint_id, thread_id))
        else:
            # Get latest checkpoint for thread
            cursor = conn.execute(f"""
                SELECT * FROM {self.table_name}
                WHERE thread_id = ?
                ORDER BY created_at DESC
                LIMIT 1
            """, (thread_id,))

        row = cursor.fetchone()
        if row is None:
            return None

        return json.loads(row["checkpoint"])

    def get_tuple(self, config: Dict[str, Any]) -> Optional[Tuple[Dict[str, Any], Dict[str, Any]]]:
        """
        Get checkpoint with metadata.

        Args:
            config: Configuration

        Returns:
            Tuple of (checkpoint, config) or None
        """
        thread_id = config.get("configurable", {}).get("thread_id")
        checkpoint_id = config.get("configurable", {}).get("checkpoint_id")

        if not thread_id:
            return None

        conn = self._get_conn()

        if checkpoint_id:
            cursor = conn.execute(f"""
                SELECT * FROM {self.table_name}
                WHERE id = ? AND thread_id = ?
            """, (checkpoint_id, thread_id))
        else:
            cursor = conn.execute(f"""
                SELECT * FROM {self.table_name}
                WHERE thread_id = ?
                ORDER BY created_at DESC
                LIMIT 1
            """, (thread_id,))

        row = cursor.fetchone()
        if row is None:
            return None

        checkpoint = json.loads(row["checkpoint"])
        result_config = {
            "configurable": {
                "thread_id": row["thread_id"],
                "checkpoint_id": row["id"],
            }
        }

        return checkpoint, result_config

    def list(
        self,
        config: Dict[str, Any],
        limit: int = 100,
        before: Optional[str] = None,
    ) -> List[CheckpointData]:
        """
        List checkpoints for a thread.

        Args:
            config: Configuration with thread_id
            limit: Maximum number of checkpoints
            before: Return checkpoints before this ID

        Returns:
            List of CheckpointData objects
        """
        thread_id = config.get("configurable", {}).get("thread_id")
        if not thread_id:
            return []

        conn = self._get_conn()

        if before:
            # Get created_at for the 'before' checkpoint
            cursor = conn.execute(f"""
                SELECT created_at FROM {self.table_name} WHERE id = ?
            """, (before,))
            row = cursor.fetchone()
            if row:
                before_time = row["created_at"]
                cursor = conn.execute(f"""
                    SELECT * FROM {self.table_name}
                    WHERE thread_id = ? AND created_at < ?
                    ORDER BY created_at DESC
                    LIMIT ?
                """, (thread_id, before_time, limit))
            else:
                cursor = conn.execute(f"""
                    SELECT * FROM {self.table_name}
                    WHERE thread_id = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                """, (thread_id, limit))
        else:
            cursor = conn.execute(f"""
                SELECT * FROM {self.table_name}
                WHERE thread_id = ?
                ORDER BY created_at DESC
                LIMIT ?
            """, (thread_id, limit))

        results = []
        for row in cursor.fetchall():
            results.append(CheckpointData(
                id=row["id"],
                thread_id=row["thread_id"],
                parent_id=row["parent_id"],
                checkpoint=json.loads(row["checkpoint"]),
                metadata=json.loads(row["metadata"]) if row["metadata"] else None,
                created_at=datetime.fromisoformat(row["created_at"]),
            ))

        return results

    def delete(self, config: Dict[str, Any]) -> bool:
        """
        Delete a checkpoint.

        Args:
            config: Configuration with checkpoint_id

        Returns:
            True if deleted
        """
        checkpoint_id = config.get("configurable", {}).get("checkpoint_id")
        if not checkpoint_id:
            return False

        conn = self._get_conn()
        cursor = conn.execute(f"""
            DELETE FROM {self.table_name} WHERE id = ?
        """, (checkpoint_id,))

        deleted = cursor.rowcount > 0
        if deleted:
            logger.debug("Deleted checkpoint %s", checkpoint_id)

        return deleted

    def clear_thread(self, thread_id: str) -> int:
        """
        Clear all checkpoints for a thread.

        Args:
            thread_id: Thread ID

        Returns:
            Number of checkpoints deleted
        """
        conn = self._get_conn()
        cursor = conn.execute(f"""
            DELETE FROM {self.table_name} WHERE thread_id = ?
        """, (thread_id,))

        count = cursor.rowcount
        logger.debug("Cleared %d checkpoints for thread %s", count, thread_id)
        return count

    def cleanup_old(self, days: int = 30) -> int:
        """
        Remove checkpoints older than specified days.

        Args:
            days: Age threshold in days

        Returns:
            Number of checkpoints deleted
        """
        from datetime import timedelta
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()

        conn = self._get_conn()
        cursor = conn.execute(f"""
            DELETE FROM {self.table_name}
            WHERE created_at < ?
        """, (cutoff,))

        count = cursor.rowcount
        logger.info("Cleaned up %d old checkpoints", count)
        return count

    def get_thread_ids(self, limit: int = 100) -> List[str]:
        """
        Get all unique thread IDs.

        Args:
            limit: Maximum number of threads

        Returns:
            List of thread IDs
        """
        conn = self._get_conn()
        cursor = conn.execute(f"""
            SELECT DISTINCT thread_id FROM {self.table_name}
            ORDER BY MAX(created_at) DESC
            LIMIT ?
        """, (limit,))

        return [row["thread_id"] for row in cursor.fetchall()]

    def get_history(
        self,
        thread_id: str,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """
        Get checkpoint history for a thread as dictionaries.

        Args:
            thread_id: Thread ID
            limit: Maximum checkpoints

        Returns:
            List of checkpoint dictionaries
        """
        checkpoints = self.list(
            {"configurable": {"thread_id": thread_id}},
            limit=limit,
        )
        return [cp.to_dict() for cp in checkpoints]
