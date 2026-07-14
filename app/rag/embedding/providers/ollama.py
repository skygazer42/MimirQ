"""
Ollama embedding model implementation.

Supports local embedding models via Ollama API.
See https://ollama.com/blog/embedding-models for available models.
"""
import httpx

from app.core.config import settings
from app.core.http_client import get_http_client_pool
from app.rag.embedding.base import BaseEmbeddingModel
from app.rag.embedding.providers._embedding_http import (
    EmbeddingHTTPConcurrency,
    post_with_retries_async,
    post_with_retries_sync,
)
from app.rag.embedding.utils import get_docker_safe_url, logger

_HTTP_CONCURRENCY = EmbeddingHTTPConcurrency("Ollama embedding")


class OllamaEmbedding(BaseEmbeddingModel):
    """Ollama local embedding model.

    Uses Ollama's local API for generating embeddings.
    Default endpoint: http://localhost:11434/api/embed

    Example models:
    - nomic-embed-text (768 dimensions)
    - bge-m3 (1024 dimensions)
    - mxbai-embed-large (1024 dimensions)
    """

    def __init__(self, **kwargs):
        """Initialize Ollama embedding model.

        Args:
            model: Ollama model name (e.g., "nomic-embed-text", "bge-m3")
            dimension: Embedding vector dimension
            base_url: Ollama API URL (default: http://localhost:11434/api/embed)
            api_key: Not used for Ollama (can be None)
        """
        super().__init__(**kwargs)
        self.base_url = self.base_url or get_docker_safe_url(
            "http://localhost:11434/api/embed"
        )

        # Use shared external HTTP clients (no internal tenant/user headers).
        pool = get_http_client_pool()
        self.http_client = pool.get_external_sync_client()
        self.http_async_client = pool.get_external_async_client()

    def _build_payload(self, message: str | list[str]) -> dict:
        """Build API request payload."""
        if isinstance(message, str):
            message = [message]
        return {"model": self.model, "input": message}

    def _validate_embeddings(self, embeddings: object) -> list[list[float]]:
        if not isinstance(embeddings, list):
            raise ValueError(f"Invalid embeddings response format: {embeddings}")
        if self.dimension:
            expected = int(self.dimension)
            for idx, vec in enumerate(embeddings):
                if not isinstance(vec, list):
                    raise ValueError(f"Invalid embedding vector at index {idx}: {type(vec)}")
                if len(vec) != expected:
                    raise ValueError(
                        f"Ollama Embedding dimension mismatch: expected {expected}, got {len(vec)}"
                    )
        return embeddings

    def _encode_one_batch(self, texts: list[str]) -> list[list[float]]:
        payload = self._build_payload(texts)
        timeout_sec = float(getattr(settings, "EMBEDDING_API_TIMEOUT_SEC", 60.0) or 60.0)
        try:
            return post_with_retries_sync(
                client=self.http_client,
                url=self.base_url,
                request_kwargs={"json": payload, "timeout": timeout_sec},
                parse_response=self._parse_response,
                concurrency=_HTTP_CONCURRENCY,
                schema_errors=(TypeError, ValueError),
            )
        except (httpx.HTTPStatusError, httpx.RequestError, TypeError, ValueError) as exc:
            msg = f"Ollama Embedding request failed: {exc}"
            logger.error("%s, payload: %s, base_url: %s", msg, payload, self.base_url)
            raise ValueError(msg) from exc

    def _parse_response(self, response: httpx.Response) -> list[list[float]]:
        result = response.json()
        if not isinstance(result, dict) or "embeddings" not in result:
            raise ValueError(f"Invalid embeddings response format: {result}")
        return self._validate_embeddings(result.get("embeddings") or [])

    def encode(self, message: str | list[str]) -> list[list[float]]:
        """Synchronously encode text(s) to embeddings."""
        if isinstance(message, str):
            texts = [message]
        else:
            texts = list(message or [])

        if not texts:
            return []

        batch_size = max(1, int(getattr(settings, "EMBEDDING_API_BATCH_SIZE", 64) or 64))
        out: list[list[float]] = []
        for start in range(0, len(texts), batch_size):
            out.extend(self._encode_one_batch(texts[start : start + batch_size]))
        return out

    async def _aencode_one_batch(self, texts: list[str]) -> list[list[float]]:
        payload = self._build_payload(texts)
        timeout_sec = float(getattr(settings, "EMBEDDING_API_TIMEOUT_SEC", 60.0) or 60.0)
        try:
            return await post_with_retries_async(
                client=self.http_async_client,
                url=self.base_url,
                request_kwargs={"json": payload, "timeout": timeout_sec},
                parse_response=self._parse_response,
                concurrency=_HTTP_CONCURRENCY,
                schema_errors=(TypeError, ValueError),
            )
        except (httpx.HTTPStatusError, httpx.RequestError, TypeError, ValueError) as exc:
            msg = f"Ollama Embedding async request failed: {exc}"
            logger.error("%s, payload: %s, base_url: %s", msg, payload, self.base_url)
            raise ValueError(msg) from exc

    async def aencode(self, message: str | list[str]) -> list[list[float]]:
        """Asynchronously encode text(s) to embeddings."""
        if isinstance(message, str):
            texts = [message]
        else:
            texts = list(message or [])

        if not texts:
            return []

        batch_size = max(1, int(getattr(settings, "EMBEDDING_API_BATCH_SIZE", 64) or 64))
        out: list[list[float]] = []
        for start in range(0, len(texts), batch_size):
            out.extend(await self._aencode_one_batch(texts[start : start + batch_size]))
        return out
