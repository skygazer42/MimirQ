"""
Ollama embedding model implementation.

Supports local embedding models via Ollama API.
See https://ollama.com/blog/embedding-models for available models.
"""
import json

import httpx
import requests

from app.rag.embedding.base import BaseEmbeddingModel, get_docker_safe_url, logger


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

    def _build_payload(self, message: str | list[str]) -> dict:
        """Build API request payload.

        Args:
            message: Text or list of texts to encode

        Returns:
            Request payload dictionary
        """
        if isinstance(message, str):
            message = [message]
        return {"model": self.model, "input": message}

    def encode(self, message: str | list[str]) -> list[list[float]]:
        """Synchronously encode text(s) to embeddings.

        Args:
            message: Single text string or list of text strings

        Returns:
            List of embedding vectors

        Raises:
            ValueError: If request fails or returns invalid response
        """
        payload = self._build_payload(message)
        try:
            response = requests.post(self.base_url, json=payload, timeout=60)
            response.raise_for_status()
            result = response.json()

            if "embeddings" not in result:
                raise ValueError(
                    f"Ollama Embedding failed: Invalid response format {result}"
                )

            return result["embeddings"]

        except (requests.RequestException, json.JSONDecodeError) as e:
            logger.error(f"Ollama Embedding request failed: {e}, payload: {payload}")
            raise ValueError(f"Ollama Embedding request failed: {e}")

    async def aencode(self, message: str | list[str]) -> list[list[float]]:
        """Asynchronously encode text(s) to embeddings.

        Args:
            message: Single text string or list of text strings

        Returns:
            List of embedding vectors

        Raises:
            ValueError: If request fails or returns invalid response
        """
        payload = self._build_payload(message)
        async with httpx.AsyncClient() as client:
            try:
                response = await client.post(self.base_url, json=payload, timeout=60)
                response.raise_for_status()
                result = response.json()

                if "embeddings" not in result:
                    raise ValueError(
                        f"Ollama Embedding failed: Invalid response format {result}"
                    )

                return result["embeddings"]

            except (httpx.RequestError, json.JSONDecodeError) as e:
                logger.error(
                    f"Ollama Embedding async request failed: {e}, "
                    f"payload: {payload}, base_url: {self.base_url}"
                )
                raise ValueError(f"Ollama Embedding async request failed: {e}")

    def encode_queries(self, queries: str | list[str]) -> list[list[float]]:
        """Encode query text(s) to embeddings.

        For Ollama, queries are encoded the same as documents.

        Args:
            queries: Single query string or list of query strings

        Returns:
            List of embedding vectors
        """
        return self.encode(queries)

    async def aencode_queries(self, queries: str | list[str]) -> list[list[float]]:
        """Asynchronously encode query text(s) to embeddings.

        Args:
            queries: Single query string or list of query strings

        Returns:
            List of embedding vectors
        """
        return await self.aencode(queries)
