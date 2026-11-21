"""Shared concurrency and retry mechanics for HTTP embedding providers."""

import asyncio
import contextlib
import math
import threading
import time
import weakref
from collections.abc import Callable, Iterator, Mapping
from datetime import UTC
from email.utils import parsedate_to_datetime
from typing import Any, Protocol, TypeVar

import httpx

from app.infrastructure.config import settings
from app.infrastructure.security.random import secure_jitter

_RETRYABLE_HTTP_CODES = frozenset({408, 429, 500, 502, 503, 504})
_REQUEST_ERRORS = (httpx.HTTPStatusError, httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError)

T = TypeVar("T")


class _SyncHTTPClient(Protocol):
    def post(self, url: str, **kwargs: Any) -> httpx.Response: ...


class _AsyncHTTPClient(Protocol):
    async def post(self, url: str, **kwargs: Any) -> httpx.Response: ...


class EmbeddingHTTPConcurrency:
    """Own provider-local sync and event-loop-local async concurrency limits."""

    def __init__(self) -> None:
        self._sync_sem: threading.BoundedSemaphore | None = None
        self._sync_sem_cap: int | None = None
        self._sync_sem_lock = threading.Lock()
        self._async_sem_by_loop: weakref.WeakKeyDictionary[
            asyncio.AbstractEventLoop,
            weakref.ReferenceType[asyncio.Semaphore],
        ] = weakref.WeakKeyDictionary()
        self._async_sem_cap: int | None = None
        self._async_sem_lock = threading.Lock()

    @staticmethod
    def _capacity() -> int:
        return settings.EMBEDDING_API_MAX_CONCURRENCY

    def _get_sync_semaphore(self) -> threading.BoundedSemaphore:
        cap = self._capacity()
        with self._sync_sem_lock:
            if self._sync_sem is None or self._sync_sem_cap != cap:
                self._sync_sem = threading.BoundedSemaphore(cap)
                self._sync_sem_cap = cap
            return self._sync_sem

    @contextlib.contextmanager
    def sync_slot(self) -> Iterator[None]:
        sem = self._get_sync_semaphore()
        sem.acquire()
        try:
            yield
        finally:
            sem.release()

    def async_semaphore(self) -> asyncio.Semaphore:
        cap = self._capacity()
        loop = asyncio.get_running_loop()

        with self._async_sem_lock:
            if self._async_sem_cap != cap:
                self._async_sem_by_loop.clear()
                self._async_sem_cap = cap
            sem_ref = self._async_sem_by_loop.get(loop)
            sem = sem_ref() if sem_ref is not None else None
            if sem is None:
                sem = asyncio.Semaphore(cap)
                self._async_sem_by_loop[loop] = weakref.ref(sem)
            return sem

    @property
    def async_pool_size(self) -> int:
        with self._async_sem_lock:
            return len(self._async_sem_by_loop)


def iter_embedding_batches(message: str | list[str], batch_size: int) -> Iterator[list[str]]:
    texts = [message] if isinstance(message, str) else message
    if not texts:
        return
    for start in range(0, len(texts), batch_size):
        yield texts[start : start + batch_size]


def _parse_retry_after_seconds(value: str | None) -> float | None:
    if not value:
        return None
    try:
        seconds = float(value)
    except ValueError:
        try:
            deadline = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=UTC)
        seconds = max(0.0, deadline.timestamp() - time.time())
    return seconds if math.isfinite(seconds) and seconds >= 0 else None


def _sleep_seconds_for_attempt(*, attempt: int, retry_after_sec: float | None) -> float:
    backoff = settings.EMBEDDING_API_RETRY_BACKOFF_SEC
    jitter = settings.EMBEDDING_API_RETRY_JITTER_SEC
    delay = backoff * (2**attempt)
    if retry_after_sec is not None:
        delay = max(delay, retry_after_sec)
    return delay + secure_jitter(jitter)


def _retry_delay(
    exc: httpx.HTTPError,
    *,
    attempt: int,
    max_retries: int,
) -> float | None:
    if attempt >= max_retries:
        return None
    retry_after = None
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status not in _RETRYABLE_HTTP_CODES:
            return None
        if status == 429:
            retry_after = _parse_retry_after_seconds(exc.response.headers.get("Retry-After"))
    return _sleep_seconds_for_attempt(attempt=attempt, retry_after_sec=retry_after)


def post_with_retries_sync(
    *,
    client: _SyncHTTPClient,
    url: str,
    request_kwargs: Mapping[str, Any],
    parse_response: Callable[[httpx.Response], T],
    concurrency: EmbeddingHTTPConcurrency,
) -> T:
    """Retry transient HTTP failures; malformed data fails after its first response."""
    max_retries = settings.EMBEDDING_API_MAX_RETRIES

    for attempt in range(max_retries + 1):
        try:
            with concurrency.sync_slot():
                response = client.post(url, **request_kwargs)
            try:
                response.raise_for_status()
                return parse_response(response)
            finally:
                response.close()
        except _REQUEST_ERRORS as exc:
            delay = _retry_delay(exc, attempt=attempt, max_retries=max_retries)
            if delay is None:
                raise
        if delay > 0:
            time.sleep(delay)


async def post_with_retries_async(
    *,
    client: _AsyncHTTPClient,
    url: str,
    request_kwargs: Mapping[str, Any],
    parse_response: Callable[[httpx.Response], T],
    concurrency: EmbeddingHTTPConcurrency,
) -> T:
    """Async counterpart to :func:`post_with_retries_sync`."""
    max_retries = settings.EMBEDDING_API_MAX_RETRIES
    sem = concurrency.async_semaphore()

    for attempt in range(max_retries + 1):
        try:
            async with sem:
                response = await client.post(url, **request_kwargs)
            try:
                response.raise_for_status()
                return parse_response(response)
            finally:
                await response.aclose()
        except _REQUEST_ERRORS as exc:
            delay = _retry_delay(exc, attempt=attempt, max_retries=max_retries)
            if delay is None:
                raise
        if delay > 0:
            await asyncio.sleep(delay)
