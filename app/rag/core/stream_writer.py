"""
StreamWriter for custom streaming output in workflows.

Provides mechanisms for real-time output during workflow execution,
tool calls, and long-running operations.

Usage:
    writer = StreamWriter()

    @task
    async def my_node(state: Dict, writer: StreamWriter) -> Dict:
        writer.write("Processing...")
        result = await do_something()
        writer.write(f"Found {len(result)} items")
        return {"result": result}
"""


import asyncio
import contextlib
import json
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from app.core.config import settings
from app.rag.core.logging import get_logger

logger = get_logger("rag.core.stream_writer")

# Configuration
STREAM_WRITER_ENABLED = getattr(settings, "STREAM_WRITER_ENABLED", True)
STREAM_BUFFER_SIZE = getattr(settings, "STREAM_BUFFER_SIZE", 100)


@dataclass
class StreamChunk:
    """
    A chunk of streaming output.

    Attributes:
        type: Chunk type (text, token, metadata, tool, error)
        content: Chunk content
        node: Source node name
        timestamp: Creation timestamp
        metadata: Additional metadata
    """
    type: str
    content: Any
    node: str | None = None
    timestamp: datetime = field(default_factory=datetime.utcnow)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "type": self.type,
            "content": self.content,
            "node": self.node,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata,
        }

    def to_sse(self) -> str:
        """Convert to Server-Sent Events format."""
        data = json.dumps(self.to_dict(), ensure_ascii=False)
        return f"data: {data}\n\n"


class BaseStreamWriter(ABC):
    """
    Abstract base class for stream writers.

    All stream writer implementations must inherit from this class.
    """

    @abstractmethod
    async def write(self, content: Any, **kwargs) -> None:
        """Write content to the stream."""
        pass

    @abstractmethod
    async def write_token(self, token: str, **kwargs) -> None:
        """Write a single token to the stream."""
        pass

    @abstractmethod
    async def write_metadata(self, metadata: dict[str, Any], **kwargs) -> None:
        """Write metadata to the stream."""
        pass

    @abstractmethod
    async def write_error(self, error: str, **kwargs) -> None:
        """Write an error to the stream."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Close the stream."""
        pass


class StreamWriter(BaseStreamWriter):
    """
    Default stream writer implementation with buffering.

    Buffers chunks and provides async iteration for consumers.
    """

    def __init__(
        self,
        buffer_size: int = STREAM_BUFFER_SIZE,
        node: str | None = None,
    ):
        """
        Initialize the stream writer.

        Args:
            buffer_size: Maximum buffer size
            node: Default node name for chunks
        """
        self._queue: asyncio.Queue[StreamChunk] = asyncio.Queue(maxsize=buffer_size)
        self._closed = False
        self._state_changed = asyncio.Event()
        self._active_writes = 0
        self._node = node
        self._listeners: list[Callable[[StreamChunk], None]] = []
        self._chunks_written = 0

    @property
    def is_closed(self) -> bool:
        """Check if the stream is closed."""
        return self._closed

    @property
    def chunks_written(self) -> int:
        """Get the number of chunks written."""
        return self._chunks_written

    def add_listener(self, callback: Callable[[StreamChunk], None]) -> None:
        """Add a listener for stream chunks."""
        self._listeners.append(callback)

    def remove_listener(self, callback: Callable[[StreamChunk], None]) -> None:
        """Remove a listener."""
        if callback in self._listeners:
            self._listeners.remove(callback)

    async def _put_chunk(self, chunk: StreamChunk) -> None:
        """Put a chunk in the queue."""
        if self._closed:
            logger.warning("Attempting to write to closed stream")
            return

        self._active_writes += 1
        try:
            await self._queue.put(chunk)
            self._chunks_written += 1

            # Notify listeners
            for listener in self._listeners:
                try:
                    listener(chunk)
                except Exception as e:
                    logger.exception("Stream listener error: %s", e)
        finally:
            self._active_writes -= 1
            self._state_changed.set()

    async def write(self, content: Any, **kwargs) -> None:
        """Write text content to the stream."""
        chunk = StreamChunk(
            type="text",
            content=str(content),
            node=kwargs.get("node", self._node),
            metadata=kwargs.get("metadata", {}),
        )
        await self._put_chunk(chunk)

    async def write_token(self, token: str, **kwargs) -> None:
        """Write a single token to the stream."""
        chunk = StreamChunk(
            type="token",
            content=token,
            node=kwargs.get("node", self._node),
            metadata=kwargs.get("metadata", {}),
        )
        await self._put_chunk(chunk)

    async def write_metadata(self, metadata: dict[str, Any], **kwargs) -> None:
        """Write metadata to the stream."""
        chunk = StreamChunk(
            type="metadata",
            content=metadata,
            node=kwargs.get("node", self._node),
            metadata=kwargs.get("extra_metadata", {}),
        )
        await self._put_chunk(chunk)

    async def write_tool_start(
        self,
        tool_name: str,
        tool_input: Any,
        **kwargs,
    ) -> None:
        """Write tool invocation start."""
        chunk = StreamChunk(
            type="tool_start",
            content={
                "tool": tool_name,
                "input": tool_input,
            },
            node=kwargs.get("node", self._node),
            metadata=kwargs.get("metadata", {}),
        )
        await self._put_chunk(chunk)

    async def write_tool_end(
        self,
        tool_name: str,
        tool_output: Any,
        **kwargs,
    ) -> None:
        """Write tool invocation result."""
        chunk = StreamChunk(
            type="tool_end",
            content={
                "tool": tool_name,
                "output": tool_output,
            },
            node=kwargs.get("node", self._node),
            metadata=kwargs.get("metadata", {}),
        )
        await self._put_chunk(chunk)

    async def write_error(self, error: str, **kwargs) -> None:
        """Write an error to the stream."""
        chunk = StreamChunk(
            type="error",
            content=error,
            node=kwargs.get("node", self._node),
            metadata=kwargs.get("metadata", {}),
        )
        await self._put_chunk(chunk)

    async def write_progress(
        self,
        current: int,
        total: int,
        message: str = "",
        **kwargs,
    ) -> None:
        """Write progress update."""
        chunk = StreamChunk(
            type="progress",
            content={
                "current": current,
                "total": total,
                "percent": (current / total * 100) if total > 0 else 0,
                "message": message,
            },
            node=kwargs.get("node", self._node),
            metadata=kwargs.get("metadata", {}),
        )
        await self._put_chunk(chunk)

    async def close(self) -> None:
        """Close the stream."""
        if self._closed:
            return

        self._closed = True
        self._state_changed.set()

    async def __aiter__(self) -> AsyncIterator[StreamChunk]:
        """Async iteration over stream chunks."""
        while True:
            if self._closed and self._active_writes == 0 and self._queue.empty():
                break
            get_task = asyncio.create_task(self._queue.get())
            state_task = asyncio.create_task(self._state_changed.wait())
            tasks = {get_task, state_task}
            try:
                done, pending = await asyncio.wait(
                    tasks,
                    return_when=asyncio.FIRST_COMPLETED,
                )
            except BaseException:
                for task in tasks:
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task
                raise
            for task in pending:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            if state_task in done:
                self._state_changed.clear()
            if get_task in done:
                yield get_task.result()

    async def read_all(self) -> list[StreamChunk]:
        """Read all chunks (waits for stream to close)."""
        chunks = []
        async for chunk in self:
            chunks.append(chunk)
        return chunks

    def drain(self) -> list[StreamChunk]:
        """Drain all currently available chunks without waiting."""
        chunks = []
        while not self._queue.empty():
            chunk = self._queue.get_nowait()
            chunks.append(chunk)
        return chunks


class CallbackStreamWriter(BaseStreamWriter):
    """
    Stream writer that calls a callback for each chunk.

    Useful for integrating with external streaming systems.
    """

    def __init__(
        self,
        callback: Callable[[StreamChunk], None],
        node: str | None = None,
    ):
        """
        Initialize with a callback function.

        Args:
            callback: Function to call for each chunk
            node: Default node name
        """
        self._callback = callback
        self._node = node
        self._closed = False

    async def _emit(self, chunk: StreamChunk) -> None:
        """Emit a chunk to the callback."""
        if self._closed:
            return
        try:
            result = self._callback(chunk)
            if asyncio.iscoroutine(result):
                await result
        except Exception as e:
            logger.exception("Callback error: %s", e)

    async def write(self, content: Any, **kwargs) -> None:
        chunk = StreamChunk(
            type="text",
            content=str(content),
            node=kwargs.get("node", self._node),
            metadata=kwargs.get("metadata", {}),
        )
        await self._emit(chunk)

    async def write_token(self, token: str, **kwargs) -> None:
        chunk = StreamChunk(
            type="token",
            content=token,
            node=kwargs.get("node", self._node),
            metadata=kwargs.get("metadata", {}),
        )
        await self._emit(chunk)

    async def write_metadata(self, metadata: dict[str, Any], **kwargs) -> None:
        chunk = StreamChunk(
            type="metadata",
            content=metadata,
            node=kwargs.get("node", self._node),
            metadata=kwargs.get("extra_metadata", {}),
        )
        await self._emit(chunk)

    async def write_error(self, error: str, **kwargs) -> None:
        chunk = StreamChunk(
            type="error",
            content=error,
            node=kwargs.get("node", self._node),
            metadata=kwargs.get("metadata", {}),
        )
        await self._emit(chunk)

    async def close(self) -> None:
        self._closed = True
        # Send close event
        chunk = StreamChunk(
            type="close",
            content=None,
            node=self._node,
        )
        await self._emit(chunk)


class NullStreamWriter(BaseStreamWriter):
    """
    Null stream writer that discards all output.

    Useful when streaming is disabled or for testing.
    """

    async def write(self, content: Any, **kwargs) -> None:
        """Intentionally no-op: NullStreamWriter discards output."""
        return None

    async def write_token(self, token: str, **kwargs) -> None:
        """Intentionally no-op: NullStreamWriter discards output."""
        return None

    async def write_metadata(self, metadata: dict[str, Any], **kwargs) -> None:
        """Intentionally no-op: NullStreamWriter discards output."""
        return None

    async def write_error(self, error: str, **kwargs) -> None:
        """Intentionally no-op: NullStreamWriter discards output."""
        return None

    async def close(self) -> None:
        """Intentionally no-op: NullStreamWriter discards output."""
        return None


class MultiStreamWriter(BaseStreamWriter):
    """
    Stream writer that writes to multiple underlying writers.

    Useful for logging and multiple consumers.
    """

    def __init__(self, writers: list[BaseStreamWriter] | None = None):
        self._writers = writers or []

    def add_writer(self, writer: BaseStreamWriter) -> None:
        """Add a writer."""
        self._writers.append(writer)

    def remove_writer(self, writer: BaseStreamWriter) -> None:
        """Remove a writer."""
        if writer in self._writers:
            self._writers.remove(writer)

    async def _broadcast(self, method: str, *args, **kwargs) -> None:
        """Broadcast a method call to all writers."""
        coros = [
            getattr(w, method)(*args, **kwargs)
            for w in self._writers
        ]
        await asyncio.gather(*coros, return_exceptions=True)

    async def write(self, content: Any, **kwargs) -> None:
        await self._broadcast("write", content, **kwargs)

    async def write_token(self, token: str, **kwargs) -> None:
        await self._broadcast("write_token", token, **kwargs)

    async def write_metadata(self, metadata: dict[str, Any], **kwargs) -> None:
        await self._broadcast("write_metadata", metadata, **kwargs)

    async def write_error(self, error: str, **kwargs) -> None:
        await self._broadcast("write_error", error, **kwargs)

    async def close(self) -> None:
        await self._broadcast("close")


def get_stream_writer(enabled: bool | None = None) -> BaseStreamWriter:
    """
    Get a stream writer based on configuration.

    Args:
        enabled: Override enabled flag

    Returns:
        StreamWriter or NullStreamWriter
    """
    if enabled is None:
        enabled = STREAM_WRITER_ENABLED

    if enabled:
        return StreamWriter()
    return NullStreamWriter()


async def stream_to_sse(
    writer: StreamWriter,
) -> AsyncIterator[str]:
    """
    Convert stream chunks to SSE format.

    Args:
        writer: Stream writer to read from

    Yields:
        SSE formatted strings
    """
    async for chunk in writer:
        yield chunk.to_sse()

    # Send close event
    yield 'data: {"type": "close"}\n\n'
