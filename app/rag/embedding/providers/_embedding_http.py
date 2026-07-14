"""Shared concurrency and retry mechanics for HTTP embedding providers."""

import asyncio
import contextlib
import threading
import time
import weakref
from collections.abc import Callable, Iterator, Mapping
from typing import Any, Protocol, TypeVar

import httpx

from app.core.config import settings
from app.core.secure_random import secure_jitter

_RETRYABLE_HTTP_CODES = frozenset({408, 429, 500, 502, 503, 504})

T = TypeVar("T")


class _SyncHTTPClient(Protocol):
    def post(self, url: str, **kwargs: Any) -> httpx.Response: ...


class _AsyncHTTPClient(Protocol):
    async def post(self, url: str, **kwargs: Any) -> httpx.Response: ...


class EmbeddingHTTPConcurrency:
    """Own provider-local sync and event-loop-local async concurrency limits."""

    def __init__(self, error_label: str) -> None:
        self._error_label = error_label
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
        return max(1, int(getattr(settings, "EMBEDDING_API_MAX_CONCURRENCY", 3) or 3))

    def _get_sync_semaphore(self) -> threading.BoundedSemaphore:
        cap = self._capacity()
        if self._sync_sem is None or self._sync_sem_cap != cap:
            with self._sync_sem_lock:
                if self._sync_sem is None or self._sync_sem_cap != cap:
                    self._sync_sem = threading.BoundedSemaphore(cap)
                    self._sync_sem_cap = cap
        if self._sync_sem is None:
            raise RuntimeError(f"{self._error_label} semaphore is not initialized")
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


def _parse_retry_after_seconds(value: str | None) -> float | None:
    if not value:
        return None
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    return seconds if seconds >= 0 else None


def _sleep_seconds_for_attempt(*, attempt: int, retry_after_sec: float | None) -> float:
    backoff = max(0.0, float(getattr(settings, "EMBEDDING_API_RETRY_BACKOFF_SEC", 0.5) or 0.5))
    jitter = max(0.0, float(getattr(settings, "EMBEDDING_API_RETRY_JITTER_SEC", 0.0) or 0.0))
    delay = backoff * (2**attempt)
    if retry_after_sec is not None:
        delay = max(delay, retry_after_sec)
    return delay + secure_jitter(jitter)


def _max_retries() -> int:
    return max(0, int(getattr(settings, "EMBEDDING_API_MAX_RETRIES", 0) or 0))


def post_with_retries_sync(
    *,
    client: _SyncHTTPClient,
    url: str,
    request_kwargs: Mapping[str, Any],
    parse_response: Callable[[httpx.Response], T],
    concurrency: EmbeddingHTTPConcurrency,
    schema_errors: tuple[type[Exception], ...],
) -> T:
    """POST and parse one batch, retrying the same failure classes as before."""
    last_exc: Exception | None = None
    max_retries = _max_retries()

    for attempt in range(max_retries + 1):
        response: httpx.Response | None = None
        try:
            with concurrency.sync_slot():
                response = client.post(url, **request_kwargs)
            response.raise_for_status()
            return parse_response(response)
        except httpx.HTTPStatusError as exc:
            last_exc = exc
            status = int(getattr(exc.response, "status_code", 0) or 0)
            if status in _RETRYABLE_HTTP_CODES and attempt < max_retries:
                retry_after = _parse_retry_after_seconds(
                    getattr(exc.response, "headers", {}).get("Retry-After")
                )
                delay = _sleep_seconds_for_attempt(
                    attempt=attempt,
                    retry_after_sec=retry_after if status == 429 else None,
                )
                with contextlib.suppress(Exception):
                    exc.response.close()
                if delay > 0:
                    time.sleep(delay)
                continue
            with contextlib.suppress(Exception):
                exc.response.close()
            break
        except httpx.RequestError as exc:
            last_exc = exc
            if attempt < max_retries:
                delay = _sleep_seconds_for_attempt(attempt=attempt, retry_after_sec=None)
                if delay > 0:
                    time.sleep(delay)
                continue
            break
        except schema_errors as exc:
            last_exc = exc
            if attempt < max_retries:
                delay = _sleep_seconds_for_attempt(attempt=attempt, retry_after_sec=None)
                if delay > 0:
                    time.sleep(delay)
                continue
            break
        finally:
            if response is not None:
                with contextlib.suppress(Exception):
                    response.close()

    if last_exc is None:
        raise RuntimeError("Embedding request failed without an exception")
    raise last_exc


async def post_with_retries_async(
    *,
    client: _AsyncHTTPClient,
    url: str,
    request_kwargs: Mapping[str, Any],
    parse_response: Callable[[httpx.Response], T],
    concurrency: EmbeddingHTTPConcurrency,
    schema_errors: tuple[type[Exception], ...],
) -> T:
    """Async counterpart to :func:`post_with_retries_sync`."""
    last_exc: Exception | None = None
    max_retries = _max_retries()
    sem = concurrency.async_semaphore()

    for attempt in range(max_retries + 1):
        response: httpx.Response | None = None
        try:
            async with sem:
                response = await client.post(url, **request_kwargs)
            response.raise_for_status()
            return parse_response(response)
        except httpx.HTTPStatusError as exc:
            last_exc = exc
            status = int(getattr(exc.response, "status_code", 0) or 0)
            if status in _RETRYABLE_HTTP_CODES and attempt < max_retries:
                retry_after = _parse_retry_after_seconds(
                    getattr(exc.response, "headers", {}).get("Retry-After")
                )
                delay = _sleep_seconds_for_attempt(
                    attempt=attempt,
                    retry_after_sec=retry_after if status == 429 else None,
                )
                with contextlib.suppress(Exception):
                    await exc.response.aclose()
                if delay > 0:
                    await asyncio.sleep(delay)
                continue
            with contextlib.suppress(Exception):
                await exc.response.aclose()
            break
        except httpx.RequestError as exc:
            last_exc = exc
            if attempt < max_retries:
                delay = _sleep_seconds_for_attempt(attempt=attempt, retry_after_sec=None)
                if delay > 0:
                    await asyncio.sleep(delay)
                continue
            break
        except schema_errors as exc:
            last_exc = exc
            if attempt < max_retries:
                delay = _sleep_seconds_for_attempt(attempt=attempt, retry_after_sec=None)
                if delay > 0:
                    await asyncio.sleep(delay)
                continue
            break
        finally:
            if response is not None:
                with contextlib.suppress(Exception):
                    await response.aclose()

    if last_exc is None:
        raise RuntimeError("Embedding request failed without an exception")
    raise last_exc
