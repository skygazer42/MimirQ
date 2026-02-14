"""
OpenAI-compatible embedding model implementation.

Supports any embedding API that follows the OpenAI embeddings format:
- OpenAI
- SiliconFlow
- DashScope (Alibaba) compatible mode
- OpenRouter
- Local vLLM
- ModelScope
- Any OpenAI-compatible endpoint
"""
import json

import httpx

from app.core.http_client import get_http_client_pool
from app.rag.embedding.base import BaseEmbeddingModel
from app.rag.embedding.utils import logger


class OpenAICompatibleEmbedding(BaseEmbeddingModel):
    """OpenAI-compatible embedding model.

    Supports any API following the OpenAI embeddings format:
    - Request: {"model": "...", "input": "..."}
    - Response: {"data": [{"embedding": [...]}]}
    """

    def __init__(self, **kwargs):
        """Initialize OpenAI-compatible embedding model.

        Args:
            model: Model name (e.g., "text-embedding-3-small", "BAAI/bge-m3")
            dimension: Embedding vector dimension
            base_url: API endpoint URL
            api_key: API key or environment variable name
        """
        super().__init__(**kwargs)

        # Setup headers
        self.headers = {"Content-Type": "application/json"}
        if self.api_key and self.api_key != "no_api_key":
            self.headers["Authorization"] = f"Bearer {self.api_key}"

        # Use shared external HTTP clients (no internal tenant/user headers).
        pool = get_http_client_pool()
        self.http_client = pool.get_external_sync_client()
        self.http_async_client = pool.get_external_async_client()

    def _build_payload(self, message: str | list[str]) -> dict:
        """Build API request payload."""
        return {"model": self.model, "input": message}

    def encode(self, message: str | list[str]) -> list[list[float]]:
        """Synchronously encode text(s) to embeddings."""
        payload = self._build_payload(message)
        try:
            response = self.http_client.post(self.base_url, json=payload, headers=self.headers, timeout=60)
            response.raise_for_status()
            result = response.json()

            if not isinstance(result, dict) or "data" not in result:
                raise ValueError(
                    f"OpenAI-compatible Embedding failed: "
                    f"Invalid response format {result}"
                )

            return [item["embedding"] for item in result["data"]]

        except (httpx.HTTPError, json.JSONDecodeError) as e:
            logger.error(
                f"OpenAI-compatible Embedding request failed: {e}, payload: {payload}"
            )
            raise ValueError(f"OpenAI-compatible Embedding request failed: {e}") from e

    async def aencode(self, message: str | list[str]) -> list[list[float]]:
        """Asynchronously encode text(s) to embeddings."""
        payload = self._build_payload(message)
        try:
            response = await self.http_async_client.post(self.base_url, json=payload, headers=self.headers, timeout=60)
            response.raise_for_status()
            result = response.json()

            if not isinstance(result, dict) or "data" not in result:
                raise ValueError(
                    f"OpenAI-compatible Embedding failed: "
                    f"Invalid response format {result}"
                )

            return [item["embedding"] for item in result["data"]]

        except (httpx.HTTPError, json.JSONDecodeError) as e:
            logger.error(
                f"OpenAI-compatible Embedding async request failed: {e}, "
                f"payload: {payload}, base_url: {self.base_url}"
            )
            raise ValueError(f"OpenAI-compatible Embedding async request failed: {e}") from e
