"""
Base embedding model abstract class.
"""
import asyncio
import hashlib
import os
from abc import ABC, abstractmethod
from typing import Optional

from app.kg.utils import get_logger

logger = get_logger("rag.embedding")


def hashstr(input_string: str, length: Optional[int] = None) -> str:
    """Generate hash of a string.

    Args:
        input_string: Input string to hash
        length: Optional length to truncate the hash to

    Returns:
        Hash string
    """
    try:
        encoded_string = str(input_string).encode("utf-8")
    except UnicodeEncodeError:
        encoded_string = str(input_string).encode("utf-8", errors="replace")

    hash_value = hashlib.md5(encoded_string).hexdigest()
    if length:
        return hash_value[:length]
    return hash_value


def get_docker_safe_url(base_url: Optional[str]) -> Optional[str]:
    """Convert URL for Docker internal networking.

    Replaces localhost/127.0.0.1 with host.docker.internal
    when running inside Docker.

    Args:
        base_url: Original URL

    Returns:
        Docker-safe URL
    """
    if not base_url:
        return base_url

    if os.getenv("RUNNING_IN_DOCKER") == "true":
        base_url = base_url.replace("http://localhost", "http://host.docker.internal")
        base_url = base_url.replace("http://127.0.0.1", "http://host.docker.internal")
        logger.info(f"Running in docker, using {base_url} as base url")
    return base_url


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
        model: Optional[str] = None,
        name: Optional[str] = None,
        dimension: Optional[int] = None,
        url: Optional[str] = None,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        model_id: Optional[str] = None,
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

    def batch_encode(
        self, messages: list[str], batch_size: int = 40
    ) -> list[list[float]]:
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

        for i in range(0, len(messages), batch_size):
            group_msg = messages[i : i + batch_size]
            logger.info(f"Encoding [{i}/{len(messages)}] messages (bsz={batch_size})")
            response = self.encode(group_msg)
            data.extend(response)
            if task_id:
                self.embed_state[task_id]["progress"] = i + len(group_msg)

        if task_id:
            self.embed_state[task_id]["status"] = "completed"

        return data

    async def abatch_encode(
        self, messages: list[str], batch_size: int = 40
    ) -> list[list[float]]:
        """Asynchronously encode messages in batches.

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

        tasks = []
        for i in range(0, len(messages), batch_size):
            group_msg = messages[i : i + batch_size]
            tasks.append(self.aencode(group_msg))

        results = await asyncio.gather(*tasks)
        for res in results:
            data.extend(res)

        if task_id:
            self.embed_state[task_id]["progress"] = len(messages)
            self.embed_state[task_id]["status"] = "completed"

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
