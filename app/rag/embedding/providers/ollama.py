"""
Ollama embedding model implementation.

Supports local embedding models via Ollama API.
See https://ollama.com/blog/embedding-models for available models.
"""
import asyncio
import contextlib
import threading
import time

import httpx

from app.core.config import settings
from app.core.http_client import get_http_client_pool
from app.core.secure_random import secure_jitter
from app.rag.embedding.base import BaseEmbeddingModel
from app.rag.embedding.utils import get_docker_safe_url, logger

_RETRYABLE_HTTP_CODES = frozenset({408, 429, 500, 502, 503, 504})

_sync_sem: threading.BoundedSemaphore | None = None
_sync_sem_cap: int | None = None
_sync_sem_lock = threading.Lock()

# Avoid cross-event-loop reuse in tests; key by loop id.
_async_sem_by_loop: dict[int, asyncio.Semaphore] = {}
_async_sem_cap: int | None = None
_async_sem_lock = threading.Lock()


def _get_sync_semaphore() -> threading.BoundedSemaphore:
    cap = max(1, int(getattr(settings, "EMBEDDING_API_MAX_CONCURRENCY", 3) or 3))
    global _sync_sem, _sync_sem_cap
    if _sync_sem is None or _sync_sem_cap != cap:
        with _sync_sem_lock:
            if _sync_sem is None or _sync_sem_cap != cap:
                _sync_sem = threading.BoundedSemaphore(cap)
                _sync_sem_cap = cap
    if _sync_sem is None:
        raise RuntimeError("Ollama embedding semaphore is not initialized")
    return _sync_sem


@contextlib.contextmanager
def _embedding_slot_sync():  # noqa: ANN202
    sem = _get_sync_semaphore()
    sem.acquire()
    try:
        yield
    finally:
        sem.release()


def _get_async_semaphore() -> asyncio.Semaphore:
    cap = max(1, int(getattr(settings, "EMBEDDING_API_MAX_CONCURRENCY", 3) or 3))
    loop = asyncio.get_running_loop()
    key = id(loop)

    global _async_sem_cap
    with _async_sem_lock:
        # If config changed, discard old semaphores to avoid stale caps.
        if _async_sem_cap != cap:
            _async_sem_by_loop.clear()
            _async_sem_cap = cap
        sem = _async_sem_by_loop.get(key)
        if sem is None:
            sem = asyncio.Semaphore(cap)
            _async_sem_by_loop[key] = sem
        return sem


def _parse_retry_after_seconds(value: str | None) -> float | None:
    if not value:
        return None
    try:
        sec = float(value)
    except (TypeError, ValueError):
        return None
    return sec if sec >= 0 else None


def _sleep_seconds_for_attempt(*, attempt: int, retry_after_sec: float | None) -> float:
    backoff = max(0.0, float(getattr(settings, "EMBEDDING_API_RETRY_BACKOFF_SEC", 0.5) or 0.5))
    jitter = max(0.0, float(getattr(settings, "EMBEDDING_API_RETRY_JITTER_SEC", 0.0) or 0.0))
    base = backoff * (2**attempt)
    if retry_after_sec is not None:
        base = max(base, retry_after_sec)
    base += secure_jitter(jitter)
    return base


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
        max_retries = max(0, int(getattr(settings, "EMBEDDING_API_MAX_RETRIES", 0) or 0))

        last_exc: Exception | None = None
        for attempt in range(max_retries + 1):
            response: httpx.Response | None = None
            try:
                with _embedding_slot_sync():
                    response = self.http_client.post(
                        self.base_url,
                        json=payload,
                        timeout=timeout_sec,
                    )
                response.raise_for_status()
                result = response.json()

                if not isinstance(result, dict) or "embeddings" not in result:
                    raise ValueError(f"Invalid embeddings response format: {result}")

                return self._validate_embeddings(result.get("embeddings") or [])

            except httpx.HTTPStatusError as exc:
                last_exc = exc
                status = int(getattr(exc.response, "status_code", 0) or 0)
                retryable = status in _RETRYABLE_HTTP_CODES
                if retryable and attempt < max_retries:
                    retry_after = _parse_retry_after_seconds(
                        getattr(exc.response, "headers", {}).get("Retry-After")
                    )
                    sleep_for = _sleep_seconds_for_attempt(
                        attempt=attempt, retry_after_sec=retry_after if status == 429 else None
                    )
                    with contextlib.suppress(Exception):
                        exc.response.close()
                    if sleep_for > 0:
                        time.sleep(sleep_for)
                    continue

                with contextlib.suppress(Exception):
                    exc.response.close()
                break

            except httpx.RequestError as exc:
                last_exc = exc
                if attempt < max_retries:
                    sleep_for = _sleep_seconds_for_attempt(attempt=attempt, retry_after_sec=None)
                    if sleep_for > 0:
                        time.sleep(sleep_for)
                    continue
                break
            except (TypeError, ValueError) as exc:
                last_exc = exc
                if attempt < max_retries:
                    sleep_for = _sleep_seconds_for_attempt(attempt=attempt, retry_after_sec=None)
                    if sleep_for > 0:
                        time.sleep(sleep_for)
                    continue
                break
            finally:
                if response is not None:
                    with contextlib.suppress(Exception):
                        response.close()

        msg = f"Ollama Embedding request failed: {last_exc}"
        logger.error("%s, payload: %s, base_url: %s", msg, payload, self.base_url)
        raise ValueError(msg) from last_exc

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
        max_retries = max(0, int(getattr(settings, "EMBEDDING_API_MAX_RETRIES", 0) or 0))

        sem = _get_async_semaphore()
        last_exc: Exception | None = None
        for attempt in range(max_retries + 1):
            response: httpx.Response | None = None
            try:
                async with sem:
                    response = await self.http_async_client.post(
                        self.base_url,
                        json=payload,
                        timeout=timeout_sec,
                    )

                response.raise_for_status()
                result = response.json()

                if not isinstance(result, dict) or "embeddings" not in result:
                    raise ValueError(f"Invalid embeddings response format: {result}")

                return self._validate_embeddings(result.get("embeddings") or [])

            except httpx.HTTPStatusError as exc:
                last_exc = exc
                status = int(getattr(exc.response, "status_code", 0) or 0)
                retryable = status in _RETRYABLE_HTTP_CODES
                if retryable and attempt < max_retries:
                    retry_after = _parse_retry_after_seconds(
                        getattr(exc.response, "headers", {}).get("Retry-After")
                    )
                    sleep_for = _sleep_seconds_for_attempt(
                        attempt=attempt, retry_after_sec=retry_after if status == 429 else None
                    )
                    with contextlib.suppress(Exception):
                        await exc.response.aclose()
                    if sleep_for > 0:
                        await asyncio.sleep(sleep_for)
                    continue

                with contextlib.suppress(Exception):
                    await exc.response.aclose()
                break

            except httpx.RequestError as exc:
                last_exc = exc
                if attempt < max_retries:
                    sleep_for = _sleep_seconds_for_attempt(attempt=attempt, retry_after_sec=None)
                    if sleep_for > 0:
                        await asyncio.sleep(sleep_for)
                    continue
                break
            except (TypeError, ValueError) as exc:
                last_exc = exc
                if attempt < max_retries:
                    sleep_for = _sleep_seconds_for_attempt(attempt=attempt, retry_after_sec=None)
                    if sleep_for > 0:
                        await asyncio.sleep(sleep_for)
                    continue
                break
            finally:
                if response is not None:
                    with contextlib.suppress(Exception):
                        await response.aclose()

        msg = f"Ollama Embedding async request failed: {last_exc}"
        logger.error("%s, payload: %s, base_url: %s", msg, payload, self.base_url)
        raise ValueError(msg) from last_exc

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
