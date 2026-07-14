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
import httpx

from app.core.config import settings
from app.core.http_client import get_http_client_pool
from app.rag.embedding.base import BaseEmbeddingModel
from app.rag.embedding.providers._embedding_http import (
    EmbeddingHTTPConcurrency,
    post_with_retries_async,
    post_with_retries_sync,
)
from app.rag.embedding.utils import logger

_DASHSCOPE_OPENAI_COMPAT_BATCH_CAP = 10
_HTTP_CONCURRENCY = EmbeddingHTTPConcurrency("OpenAI embedding")


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

    def _effective_batch_size(self) -> int:
        configured = max(1, int(getattr(settings, "EMBEDDING_API_BATCH_SIZE", 64) or 64))
        base_url = str(self.base_url or "").lower()
        if "dashscope.aliyuncs.com" in base_url:
            return min(configured, _DASHSCOPE_OPENAI_COMPAT_BATCH_CAP)
        return configured

    def _encode_one_batch(self, texts: list[str]) -> list[list[float]]:
        payload = self._build_payload(texts)
        timeout_sec = float(getattr(settings, "EMBEDDING_API_TIMEOUT_SEC", 60.0) or 60.0)
        try:
            return post_with_retries_sync(
                client=self.http_client,
                url=self.base_url,
                request_kwargs={
                    "json": payload,
                    "headers": self.headers,
                    "timeout": timeout_sec,
                },
                parse_response=self._parse_response,
                concurrency=_HTTP_CONCURRENCY,
                schema_errors=(KeyError, TypeError, ValueError),
            )
        except (httpx.HTTPStatusError, httpx.RequestError, KeyError, TypeError, ValueError) as exc:
            msg = f"OpenAI-compatible Embedding request failed: {exc}"
            logger.error("%s, payload: %s", msg, payload)
            raise ValueError(msg) from exc

    @staticmethod
    def _parse_response(response: httpx.Response) -> list[list[float]]:
        result = response.json()
        if not isinstance(result, dict) or "data" not in result:
            raise ValueError(f"Invalid embeddings response format: {result}")
        data = result.get("data") or []
        return [item["embedding"] for item in data]

    def encode(self, message: str | list[str]) -> list[list[float]]:
        """Synchronously encode text(s) to embeddings."""
        if isinstance(message, str):
            texts = [message]
        else:
            texts = list(message or [])

        if not texts:
            return []

        batch_size = self._effective_batch_size()
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
                request_kwargs={
                    "json": payload,
                    "headers": self.headers,
                    "timeout": timeout_sec,
                },
                parse_response=self._parse_response,
                concurrency=_HTTP_CONCURRENCY,
                schema_errors=(KeyError, TypeError, ValueError),
            )
        except (httpx.HTTPStatusError, httpx.RequestError, KeyError, TypeError, ValueError) as exc:
            msg = f"OpenAI-compatible Embedding async request failed: {exc}"
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

        batch_size = self._effective_batch_size()
        out: list[list[float]] = []
        for start in range(0, len(texts), batch_size):
            out.extend(await self._aencode_one_batch(texts[start : start + batch_size]))
        return out
