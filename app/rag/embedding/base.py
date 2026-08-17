"""
Base embedding model abstract class.
"""

import asyncio
import os
from abc import ABC, abstractmethod

from app.rag.embedding.utils import get_docker_safe_url, hashstr, logger


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
    ):
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
        self.base_url = get_docker_safe_url(base_url)
        self.api_key = os.getenv(api_key, api_key) if api_key else None
        self.embed_state: dict = {}

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
        data = []
        task_id = None

        if len(messages) > batch_size:
            task_id = hashstr(str(messages))
            self.embed_state[task_id] = {
                "status": "in-progress",
                "total": len(messages),
                "progress": 0,
            }

        try:
            for i in range(0, len(messages), batch_size):
                group_msg = messages[i : i + batch_size]
                logger.info(f"Encoding [{i}/{len(messages)}] messages (bsz={batch_size})")
                response = self.encode(group_msg)
                data.extend(response)
                if task_id:
                    self.embed_state[task_id]["progress"] = i + len(group_msg)
        except Exception:
            if task_id:
                self.embed_state[task_id]["status"] = "failed"
            raise
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
        if not messages:
            return []

        data = []
        task_id = None

        if len(messages) > batch_size:
            task_id = hashstr(str(messages))
            self.embed_state[task_id] = {
                "status": "in-progress",
                "total": len(messages),
                "progress": 0,
            }

        # Split into batches
        batches = []
        for i in range(0, len(messages), batch_size):
            group_msg = messages[i : i + batch_size]
            batches.append((i, group_msg))

        # Process with concurrent control using semaphore
        semaphore = asyncio.Semaphore(max_concurrent)

        async def encode_batch_with_limit(batch_info):
            idx, group_msg = batch_info
            async with semaphore:
                logger.info(
                    f"Encoding batch [{idx}/{len(messages)}] (bsz={len(group_msg)}, concurrent={max_concurrent})"
                )
                result = await self.aencode(group_msg)
                if task_id:
                    self.embed_state[task_id]["progress"] = min(idx + len(group_msg), len(messages))
                return result

        tasks = [encode_batch_with_limit(batch) for batch in batches]
        try:
            results = await asyncio.gather(*tasks)
        except Exception:
            # A failed batch fails the whole call (results must stay aligned);
            # mark the task failed instead of leaving it stuck at "in-progress".
            if task_id:
                self.embed_state[task_id]["status"] = "failed"
            raise
        finally:
            # embed_state is progress bookkeeping only; drop the entry so a
            # long-lived embedder does not accumulate an unbounded dict.
            if task_id:
                self.embed_state.pop(task_id, None)

        for res in results:
            data.extend(res)

        return data

    async def test_connection(self) -> tuple[bool, str]:
        """Test the embedding model connection.

        Returns:
            Tuple of (success: bool, message: str)
        """
        try:
            test_text = ["Hello world"]
            await self.aencode(test_text)
            return True, "Connection successful"
        except Exception as e:
            error_msg = str(e)
            error_msg += (
                f", please verify `{self.base_url}` is accessible "
                "and ends with appropriate endpoint (e.g., /embeddings)"
            )
            logger.error(error_msg)
            return False, error_msg
