"""
Ollama embedding model implementation.

Supports local embedding models via Ollama API.
See https://ollama.com/blog/embedding-models for available models.
"""

from typing import Unpack

import httpx

from app.infrastructure.config import settings
from app.infrastructure.http.client import get_http_client_pool
from app.rag.embedding.base import BaseEmbeddingModel, EmbeddingModelOptions
from app.rag.embedding.providers._embedding_http import (
    EmbeddingHTTPConcurrency,
    iter_embedding_batches,
    post_with_retries_async,
    post_with_retries_sync,
)
from app.rag.embedding.utils import get_docker_safe_url, logger, validate_embedding_vectors

_HTTP_CONCURRENCY = EmbeddingHTTPConcurrency()


class OllamaEmbedding(BaseEmbeddingModel):
    """Ollama local embedding model.

    Uses Ollama's local API for generating embeddings.
    Default endpoint: http://localhost:11434/api/embed

    Example models:
    - nomic-embed-text (768 dimensions)
    - bge-m3 (1024 dimensions)
    - mxbai-embed-large (1024 dimensions)
    """

    def __init__(
        self,
        *,
        http_client: httpx.Client | None = None,
        http_async_client: httpx.AsyncClient | None = None,
        **kwargs: Unpack[EmbeddingModelOptions],
    ) -> None:
        """Initialize Ollama embedding model.

        Args:
            model: Ollama model name (e.g., "nomic-embed-text", "bge-m3")
            dimension: Embedding vector dimension
            base_url: Ollama API URL (default: http://localhost:11434/api/embed)
            api_key: Not used for Ollama (can be None)
        """
        super().__init__(**kwargs)
        self.base_url = self.base_url or get_docker_safe_url("http://localhost:11434/api/embed")

        # Use shared external HTTP clients (no internal tenant/user headers).
        self.http_client = http_client if http_client is not None else get_http_client_pool().get_external_sync_client()
        self.http_async_client = (
            http_async_client if http_async_client is not None else get_http_client_pool().get_external_async_client()
        )

    def _build_payload(self, message: str | list[str]) -> dict[str, str | list[str] | None]:
        """Build API request payload."""
        if isinstance(message, str):
            message = [message]
        return {"model": self.model, "input": message}

    def _encode_one_batch(self, texts: list[str]) -> list[list[float]]:
        payload = self._build_payload(texts)
        timeout_sec = settings.EMBEDDING_API_TIMEOUT_SEC
        try:
            return post_with_retries_sync(
                client=self.http_client,
                url=self.base_url,
                request_kwargs={"json": payload, "timeout": timeout_sec},
                parse_response=lambda response: self._parse_response(response, count=len(texts)),
                concurrency=_HTTP_CONCURRENCY,
            )
        except (httpx.HTTPStatusError, httpx.RequestError, TypeError, ValueError) as exc:
            msg = f"Ollama Embedding request failed: {exc}"
            logger.error("%s", msg)
            raise ValueError(msg) from exc

    def _parse_response(self, response: httpx.Response, *, count: int) -> list[list[float]]:
        result = response.json()
        if not isinstance(result, dict) or "embeddings" not in result:
            raise ValueError("Ollama response must contain an embeddings array")
        return validate_embedding_vectors(result["embeddings"], count=count, dimension=self.dimension)

    def encode(self, message: str | list[str]) -> list[list[float]]:
        """Synchronously encode text(s) to embeddings."""
        out: list[list[float]] = []
        for batch in iter_embedding_batches(message, settings.EMBEDDING_API_BATCH_SIZE):
            out.extend(self._encode_one_batch(batch))
        return out

    async def _aencode_one_batch(self, texts: list[str]) -> list[list[float]]:
        payload = self._build_payload(texts)
        timeout_sec = settings.EMBEDDING_API_TIMEOUT_SEC
        try:
            return await post_with_retries_async(
                client=self.http_async_client,
                url=self.base_url,
                request_kwargs={"json": payload, "timeout": timeout_sec},
                parse_response=lambda response: self._parse_response(response, count=len(texts)),
                concurrency=_HTTP_CONCURRENCY,
            )
        except (httpx.HTTPStatusError, httpx.RequestError, TypeError, ValueError) as exc:
            msg = f"Ollama Embedding async request failed: {exc}"
            logger.error("%s", msg)
            raise ValueError(msg) from exc

    async def aencode(self, message: str | list[str]) -> list[list[float]]:
        """Asynchronously encode text(s) to embeddings."""
        out: list[list[float]] = []
        for batch in iter_embedding_batches(message, settings.EMBEDDING_API_BATCH_SIZE):
            out.extend(await self._aencode_one_batch(batch))
        return out
