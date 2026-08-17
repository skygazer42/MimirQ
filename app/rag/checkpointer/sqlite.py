"""
SQLite-based LangGraph checkpointer.

A lightweight alternative to `langgraph-checkpoint-sqlite`, suitable for local/development environments,
and compatible with LangGraph's `BaseCheckpointSaver` interface.
"""

import re
import sqlite3
import threading
from collections.abc import AsyncIterator, Iterator, Sequence
from pathlib import Path
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    WRITES_IDX_MAP,
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    get_checkpoint_id,
    get_checkpoint_metadata,
)

from app.core.config import settings
from app.rag.core.logging import get_logger

logger = get_logger(__name__)


class SqliteSaver(BaseCheckpointSaver[str]):
    """
    SQLite checkpointer for LangGraph.

    Stores checkpoints + pending writes keyed by:
      (thread_id, checkpoint_ns, checkpoint_id)
    """

    def __init__(
        self,
        db_path: str | None = None,
        *,
        table_prefix: str = "langgraph",
        serde=None,
    ) -> None:
        super().__init__(serde=serde)
        # Validate table_prefix to prevent SQL injection
        if not re.match(r"^[A-Za-z_]\w*$", table_prefix, flags=re.ASCII):
            raise ValueError(
                f"Invalid table_prefix '{table_prefix}': must be alphanumeric with underscores only"
            )
        self.db_path = db_path or getattr(settings, "CHECKPOINT_SQLITE_PATH", "./data/checkpoints.db")
        self.table_prefix = table_prefix
        self._local = threading.local()
        self._lock = threading.RLock()
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            return conn

        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(
            self.db_path,
            check_same_thread=False,
            isolation_level=None,
        )
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA synchronous=NORMAL;")
        except Exception as exc:
            logger.debug("Ignoring SQLite checkpointer PRAGMA setup failure: %s", exc)
        self._local.conn = conn
        return conn

    @property
    def _checkpoints_table(self) -> str:
        return f"{self.table_prefix}_checkpoints"

    @property
    def _writes_table(self) -> str:
        return f"{self.table_prefix}_writes"

    def _init_db(self) -> None:
        with self._lock:
            conn = self._get_conn()
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self._checkpoints_table} (
                    thread_id TEXT NOT NULL,
                    checkpoint_ns TEXT NOT NULL,
                    checkpoint_id TEXT NOT NULL,
                    parent_checkpoint_id TEXT,
                    checkpoint_type TEXT NOT NULL,
                    checkpoint_blob BLOB NOT NULL,
                    metadata_type TEXT NOT NULL,
                    metadata_blob BLOB NOT NULL,
                    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
                )
                """
            )
            conn.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idx_{self._checkpoints_table}_thread
                ON {self._checkpoints_table}(thread_id, checkpoint_ns, checkpoint_id)
                """
            )
            conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self._writes_table} (
                    thread_id TEXT NOT NULL,
                    checkpoint_ns TEXT NOT NULL,
                    checkpoint_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    write_idx INTEGER NOT NULL,
                    channel TEXT NOT NULL,
                    value_type TEXT NOT NULL,
                    value_blob BLOB NOT NULL,
                    task_path TEXT,
                    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, write_idx)
                )
                """
            )
            conn.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idx_{self._writes_table}_thread
                ON {self._writes_table}(thread_id, checkpoint_ns, checkpoint_id)
                """
            )

    def _load_pending_writes(
        self,
        conn: sqlite3.Connection,
        *,
        thread_id: str,
        checkpoint_ns: str,
        checkpoint_id: str,
    ) -> list[tuple[str, str, Any]]:
        writes_rows = conn.execute(
            (
                "SELECT task_id, channel, value_type, value_blob "  # noqa: S608 - table_prefix is validated at initialization.
                f"FROM {self._writes_table} "
                "WHERE thread_id = ? AND checkpoint_ns = ? AND checkpoint_id = ? "
                "ORDER BY write_idx ASC"
            ),
            (thread_id, checkpoint_ns, checkpoint_id),
        ).fetchall()
        return [
            (r["task_id"], r["channel"], self.serde.loads_typed((r["value_type"], r["value_blob"])))
            for r in (writes_rows or [])
        ]

    @staticmethod
    def _build_parent_config(
        *,
        thread_id: str,
        checkpoint_ns: str,
        parent_checkpoint_id: str | None,
    ) -> RunnableConfig | None:
        if not parent_checkpoint_id:
            return None
        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": parent_checkpoint_id,
            }
        }

    def _build_checkpoint_tuple(
        self,
        *,
        thread_id: str,
        checkpoint_ns: str,
        checkpoint_id: str,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        parent_checkpoint_id: str | None,
        pending_writes: list[tuple[str, str, Any]],
    ) -> CheckpointTuple:
        return CheckpointTuple(
            config={
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": checkpoint_ns,
                    "checkpoint_id": checkpoint_id,
                }
            },
            checkpoint=checkpoint,
            metadata=metadata,
            parent_config=self._build_parent_config(
                thread_id=thread_id,
                checkpoint_ns=checkpoint_ns,
                parent_checkpoint_id=parent_checkpoint_id,
            ),
            pending_writes=pending_writes,
        )

    def _thread_ids_for_list(
        self,
        conn: sqlite3.Connection,
        config: RunnableConfig | None,
    ) -> Sequence[str]:
        if config is not None:
            return [config["configurable"]["thread_id"]]
        rows = conn.execute(f"SELECT DISTINCT thread_id FROM {self._checkpoints_table}").fetchall()  # noqa: S608 - SQL identifiers are quoted/validated; values stay parameterized.
        return [r["thread_id"] for r in rows]

    @staticmethod
    def _checkpoint_matches_list_request(
        checkpoint_id: str,
        *,
        config_checkpoint_id: str | None,
        before_checkpoint_id: str | None,
    ) -> bool:
        if config_checkpoint_id and checkpoint_id != config_checkpoint_id:
            return False
        if before_checkpoint_id and checkpoint_id >= before_checkpoint_id:
            return False
        return True

    @staticmethod
    def _metadata_matches_filter(
        metadata: CheckpointMetadata,
        filter: dict[str, Any] | None,
    ) -> bool:
        return not filter or all(metadata.get(k) == v for k, v in filter.items())

    def get_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        thread_id: str = config["configurable"]["thread_id"]
        checkpoint_ns: str = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id = get_checkpoint_id(config)

        conn = self._get_conn()
        if checkpoint_id:
            row = conn.execute(
                (
                    "SELECT checkpoint_type, checkpoint_blob, metadata_type, metadata_blob, parent_checkpoint_id "  # noqa: S608 - table_prefix is validated at initialization.
                    f"FROM {self._checkpoints_table} "
                    "WHERE thread_id = ? AND checkpoint_ns = ? AND checkpoint_id = ?"
                ),
                (thread_id, checkpoint_ns, checkpoint_id),
            ).fetchone()
        else:
            row = conn.execute(
                (
                    "SELECT checkpoint_id, checkpoint_type, checkpoint_blob, metadata_type, metadata_blob, parent_checkpoint_id "  # noqa: S608 - table_prefix is validated at initialization.
                    f"FROM {self._checkpoints_table} "
                    "WHERE thread_id = ? AND checkpoint_ns = ? "
                    "ORDER BY checkpoint_id DESC "
                    "LIMIT 1"
                ),
                (thread_id, checkpoint_ns),
            ).fetchone()
            checkpoint_id = row["checkpoint_id"] if row else None

        if not row or not checkpoint_id:
            return None

        checkpoint: Checkpoint = self.serde.loads_typed((row["checkpoint_type"], row["checkpoint_blob"]))
        metadata: CheckpointMetadata = self.serde.loads_typed((row["metadata_type"], row["metadata_blob"]))
        parent_checkpoint_id = row["parent_checkpoint_id"]
        pending_writes = self._load_pending_writes(
            conn,
            thread_id=thread_id,
            checkpoint_ns=checkpoint_ns,
            checkpoint_id=checkpoint_id,
        )

        return self._build_checkpoint_tuple(
            thread_id=thread_id,
            checkpoint_ns=checkpoint_ns,
            checkpoint_id=checkpoint_id,
            checkpoint=checkpoint,
            metadata=metadata,
            parent_checkpoint_id=parent_checkpoint_id,
            pending_writes=pending_writes,
        )

    def list(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> Iterator[CheckpointTuple]:
        conn = self._get_conn()
        thread_ids = self._thread_ids_for_list(conn, config)

        before_checkpoint_id = get_checkpoint_id(before) if before else None
        config_checkpoint_ns = config["configurable"].get("checkpoint_ns") if config else None
        config_checkpoint_id = get_checkpoint_id(config) if config else None

        remaining = limit

        for thread_id in thread_ids:
            ns_rows = conn.execute(
                f"SELECT DISTINCT checkpoint_ns FROM {self._checkpoints_table} WHERE thread_id = ?",  # noqa: S608 - SQL identifiers are quoted/validated; values stay parameterized.
                (thread_id,),
            ).fetchall()
            namespaces = [r["checkpoint_ns"] for r in ns_rows]

            for checkpoint_ns in namespaces:
                if config_checkpoint_ns is not None and checkpoint_ns != config_checkpoint_ns:
                    continue

                rows = conn.execute(
                    (
                        "SELECT checkpoint_id, checkpoint_type, checkpoint_blob, metadata_type, metadata_blob, parent_checkpoint_id "  # noqa: S608 - table_prefix is validated at initialization.
                        f"FROM {self._checkpoints_table} "
                        "WHERE thread_id = ? AND checkpoint_ns = ? "
                        "ORDER BY checkpoint_id DESC"
                    ),
                    (thread_id, checkpoint_ns),
                ).fetchall()

                for row in rows:
                    checkpoint_id = row["checkpoint_id"]
                    if not self._checkpoint_matches_list_request(
                        checkpoint_id,
                        config_checkpoint_id=config_checkpoint_id,
                        before_checkpoint_id=before_checkpoint_id,
                    ):
                        continue

                    metadata: CheckpointMetadata = self.serde.loads_typed((row["metadata_type"], row["metadata_blob"]))
                    if not self._metadata_matches_filter(metadata, filter):
                        continue

                    if remaining is not None and remaining <= 0:
                        return
                    if remaining is not None:
                        remaining -= 1

                    checkpoint: Checkpoint = self.serde.loads_typed((row["checkpoint_type"], row["checkpoint_blob"]))
                    parent_checkpoint_id = row["parent_checkpoint_id"]
                    pending_writes = self._load_pending_writes(
                        conn,
                        thread_id=thread_id,
                        checkpoint_ns=checkpoint_ns,
                        checkpoint_id=checkpoint_id,
                    )

                    yield self._build_checkpoint_tuple(
                        thread_id=thread_id,
                        checkpoint_ns=checkpoint_ns,
                        checkpoint_id=checkpoint_id,
                        checkpoint=checkpoint,
                        metadata=metadata,
                        parent_checkpoint_id=parent_checkpoint_id,
                        pending_writes=pending_writes,
                    )

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        _ = new_versions
        thread_id: str = config["configurable"]["thread_id"]
        checkpoint_ns: str = config["configurable"].get("checkpoint_ns", "")
        parent_checkpoint_id = config["configurable"].get("checkpoint_id")
        checkpoint_id = checkpoint["id"]

        checkpoint_type, checkpoint_blob = self.serde.dumps_typed(checkpoint)
        md = get_checkpoint_metadata(config, metadata)
        metadata_type, metadata_blob = self.serde.dumps_typed(md)

        conn = self._get_conn()
        conn.execute(
            f"""
            INSERT OR REPLACE INTO {self._checkpoints_table}
            (thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, checkpoint_type, checkpoint_blob, metadata_type, metadata_blob)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                thread_id,
                checkpoint_ns,
                checkpoint_id,
                parent_checkpoint_id,
                checkpoint_type,
                checkpoint_blob,
                metadata_type,
                metadata_blob,
            ),
        )

        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint_id,
            }
        }

    def put_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        thread_id: str = config["configurable"]["thread_id"]
        checkpoint_ns: str = config["configurable"].get("checkpoint_ns", "")
        checkpoint_id: str = config["configurable"]["checkpoint_id"]
        conn = self._get_conn()

        for idx, (channel, value) in enumerate(writes):
            write_idx = WRITES_IDX_MAP.get(channel, idx)
            value_type, value_blob = self.serde.dumps_typed(value)

            if write_idx >= 0:
                sql = (
                    f"INSERT OR IGNORE INTO {self._writes_table} "  # noqa: S608 - SQL identifiers are quoted/validated; values stay parameterized.
                    "(thread_id, checkpoint_ns, checkpoint_id, task_id, write_idx, channel, value_type, value_blob, task_path) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
                )
            else:
                sql = (
                    f"INSERT OR REPLACE INTO {self._writes_table} "  # noqa: S608 - SQL identifiers are quoted/validated; values stay parameterized.
                    "(thread_id, checkpoint_ns, checkpoint_id, task_id, write_idx, channel, value_type, value_blob, task_path) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
                )

            conn.execute(
                sql,
                (
                    thread_id,
                    checkpoint_ns,
                    checkpoint_id,
                    task_id,
                    write_idx,
                    channel,
                    value_type,
                    value_blob,
                    task_path,
                ),
            )

    def delete_thread(self, thread_id: str) -> None:
        conn = self._get_conn()
        conn.execute(f"DELETE FROM {self._writes_table} WHERE thread_id = ?", (thread_id,))  # noqa: S608 - SQL identifiers are quoted/validated; values stay parameterized.
        conn.execute(f"DELETE FROM {self._checkpoints_table} WHERE thread_id = ?", (thread_id,))  # noqa: S608 - SQL identifiers are quoted/validated; values stay parameterized.

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        return self.get_tuple(config)

    async def alist(
        self,
        config: RunnableConfig | None,
        *,
        filter: dict[str, Any] | None = None,
        before: RunnableConfig | None = None,
        limit: int | None = None,
    ) -> AsyncIterator[CheckpointTuple]:
        for item in self.list(config, filter=filter, before=before, limit=limit):
            yield item

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        return self.put(config, checkpoint, metadata, new_versions)

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        return self.put_writes(config, writes, task_id, task_path)

    async def adelete_thread(self, thread_id: str) -> None:
        return self.delete_thread(thread_id)
