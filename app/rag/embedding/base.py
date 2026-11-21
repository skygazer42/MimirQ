"""
Base embedding model abstract class.
"""

import asyncio
import os
from abc import ABC, abstractmethod
from typing import TypedDict
from uuid import uuid4

from app.rag.embedding.utils import get_docker_safe_url, logger, validate_embedding_vectors


class EmbeddingModelOptions(TypedDict, total=False):
    model: str | None
    name: str | None
    dimension: int | None
    url: str | None
    base_url: str | None
    api_key: str | None
    model_id: str | None


class EmbeddingBatchProgress(TypedDict):
    status: str
    total: int
    progress: int


class BaseEmbeddingModel(ABC):
    """Abstract base class for embedding models.

    All embedding implementations should inherit from this class
    and implement the encode and aencode methods.

    Attributes:
        model: Model name
        dimension: Embedding vector dimension
        base_url: API endpoint URL
        api_key: API key for authentication
        embed_state: State tracking for batch operations
    """

    def __init__(
        self,
        model: str | None = None,
        name: str | None = None,
        dimension: int | None = None,
        url: str | None = None,
        base_url: str | None = None,
        api_key: str | None = None,
        model_id: str | None = None,
    ) -> None:
        """Initialize embedding model.

        Args:
            model: Model name (legacy, same as name)
            name: Model name
            dimension: Embedding vector dimension
            url: API URL (legacy, same as base_url)
            base_url: API endpoint URL
            api_key: API key or environment variable name
            model_id: Optional model identifier
        """
        base_url = base_url or url
        self.model = model or name
        self.dimension = dimension
        if dimension is not None and dimension < 1:
            raise ValueError("Embedding dimension must be positive")
        self.base_url = get_docker_safe_url(base_url)
        self.api_key = os.getenv(api_key, api_key) if api_key else None
        self.embed_state: dict[str, EmbeddingBatchProgress] = {}

    @abstractmethod
    def encode(self, message: str | list[str]) -> list[list[float]]:
        """Synchronously encode text(s) to embeddings.

        Args:
            message: Single text string or list of text strings

        Returns:
            List of embedding vectors (list of floats)
        """
        raise NotImplementedError("Subclasses must implement encode method")

    def encode_queries(self, queries: str | list[str]) -> list[list[float]]:
        """Encode query text(s) to embeddings.

        Alias for encode - some models may treat queries differently.

        Args:
            queries: Single query string or list of query strings

        Returns:
            List of embedding vectors
        """
        return self.encode(queries)

    @abstractmethod
    async def aencode(self, message: str | list[str]) -> list[list[float]]:
        """Asynchronously encode text(s) to embeddings.

        Args:
            message: Single text string or list of text strings

        Returns:
            List of embedding vectors
        """
        raise NotImplementedError("Subclasses must implement aencode method")

    async def aencode_queries(self, queries: str | list[str]) -> list[list[float]]:
        """Asynchronously encode query text(s) to embeddings.

        Alias for aencode.

        Args:
            queries: Single query string or list of query strings

        Returns:
            List of embedding vectors
        """
        return await self.aencode(queries)

    def batch_encode(self, messages: list[str], batch_size: int = 40) -> list[list[float]]:
        """Encode messages in batches.

        Args:
            messages: List of text strings to encode
            batch_size: Number of messages per batch

        Returns:
            List of embedding vectors
        """
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        data = []
        task_id = None

        if len(messages) > batch_size:
            task_id = uuid4().hex
            self.embed_state[task_id] = {
                "status": "in-progress",
                "total": len(messages),
                "progress": 0,
            }

        try:
            for i in range(0, len(messages), batch_size):
                group_msg = messages[i : i + batch_size]
                logger.info("Encoding [%s/%s] messages (bsz=%s)", i, len(messages), batch_size)
                response = self.encode(group_msg)
                data.extend(response)
                if task_id:
                    self.embed_state[task_id]["progress"] = i + len(group_msg)
        finally:
            # embed_state is progress bookkeeping only; drop the entry so a
            # long-lived embedder does not accumulate an unbounded dict.
            if task_id:
                self.embed_state.pop(task_id, None)

        return data

    async def abatch_encode(
        self, messages: list[str], batch_size: int = 40, max_concurrent: int = 3
    ) -> list[list[float]]:
        """Asynchronously encode messages in batches with concurrent control.

        Args:
            messages: List of text strings to encode
            batch_size: Number of messages per batch
            max_concurrent: Maximum number of concurrent API calls (default: 3)

        Returns:
            List of embedding vectors
        """
        if batch_size < 1 or max_concurrent < 1:
            raise ValueError("batch_size and max_concurrent must be positive")
        if not messages:
            return []

        task_id = None

        if len(messages) > batch_size:
            task_id = uuid4().hex
            self.embed_state[task_id] = {
                "status": "in-progress",
                "total": len(messages),
                "progress": 0,
            }

        semaphore = asyncio.Semaphore(max_concurrent)

        async def encode_batch_with_limit(start: int, batch: list[str]) -> list[list[float]]:
            async with semaphore:
                logger.info(
                    "Encoding batch [%s/%s] (bsz=%s, concurrent=%s)", start, len(messages), len(batch), max_concurrent
                )
                result = await self.aencode(batch)
                if task_id:
                    self.embed_state[task_id]["progress"] += len(batch)
                return result

        tasks: list[asyncio.Task[list[list[float]]]] = []
        try:
            for start in range(0, len(messages), batch_size):
                batch_coro = encode_batch_with_limit(start, messages[start : start + batch_size])
                try:
                    tasks.append(asyncio.create_task(batch_coro))
                except BaseException:
                    batch_coro.close()
                    raise
            results = await asyncio.gather(*tasks)
        except BaseException:
            for task in tasks:
                if not task.cancelling():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        finally:
            # embed_state is progress bookkeeping only; drop the entry so a
            # long-lived embedder does not accumulate an unbounded dict.
            if task_id:
                self.embed_state.pop(task_id, None)

        return [vector for batch_result in results for vector in batch_result]

    async def test_connection(self) -> tuple[bool, str]:
        """Test the embedding model connection.

        Returns:
            Tuple of (success: bool, message: str)
        """
        try:
            test_text = ["Hello world"]
            vectors = await self.aencode(test_text)
            validate_embedding_vectors(vectors, count=1, dimension=self.dimension)
            return True, "Connection successful"
        except Exception as e:
            error_msg = str(e)
            error_msg += (
                f", please verify `{self.base_url}` is accessible "
                "and ends with appropriate endpoint (e.g., /embeddings)"
            )
            logger.error(error_msg)
            return False, error_msg
