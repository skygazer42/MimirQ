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
import asyncio
import contextlib
import threading
import time

import httpx

from app.core.config import settings
from app.core.http_client import get_http_client_pool
from app.core.secure_random import secure_jitter
from app.rag.embedding.base import BaseEmbeddingModel
from app.rag.embedding.utils import logger

_RETRYABLE_HTTP_CODES = frozenset({408, 429, 500, 502, 503, 504})
_DASHSCOPE_OPENAI_COMPAT_BATCH_CAP = 10

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
    assert _sync_sem is not None
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
        max_retries = max(0, int(getattr(settings, "EMBEDDING_API_MAX_RETRIES", 0) or 0))

        last_exc: Exception | None = None
        for attempt in range(max_retries + 1):
            response: httpx.Response | None = None
            try:
                with _embedding_slot_sync():
                    response = self.http_client.post(
                        self.base_url,
                        json=payload,
                        headers=self.headers,
                        timeout=timeout_sec,
                    )
                response.raise_for_status()
                result = response.json()

                if not isinstance(result, dict) or "data" not in result:
                    raise ValueError(f"Invalid embeddings response format: {result}")

                data = result.get("data") or []
                return [item["embedding"] for item in data]

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
                    # Release connection before sleeping.
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
            except (KeyError, TypeError, ValueError) as exc:
                # Do not aggressively retry schema issues; but treat as retryable when the server
                # returns partial/bad JSON under load (best-effort).
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

        msg = f"OpenAI-compatible Embedding request failed: {last_exc}"
        logger.error("%s, payload: %s", msg, payload)
        raise ValueError(msg) from last_exc

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
                        headers=self.headers,
                        timeout=timeout_sec,
                    )

                response.raise_for_status()
                result = response.json()

                if not isinstance(result, dict) or "data" not in result:
                    raise ValueError(f"Invalid embeddings response format: {result}")

                data = result.get("data") or []
                return [item["embedding"] for item in data]

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
            except (KeyError, TypeError, ValueError) as exc:
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

        msg = f"OpenAI-compatible Embedding async request failed: {last_exc}"
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

        batch_size = self._effective_batch_size()
        out: list[list[float]] = []
        for start in range(0, len(texts), batch_size):
            out.extend(await self._aencode_one_batch(texts[start : start + batch_size]))
        return out
