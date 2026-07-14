"""Thread-safe lazy Redis client slots for optional backend features."""

import threading
from collections.abc import Callable, Mapping
from typing import Any


class LazyRedisClient:
    """Build one Redis client lazily and allow callers to invalidate it on I/O errors."""

    def __init__(
        self,
        *,
        url: str | Callable[[], str],
        kwargs: Mapping[str, Any] | None = None,
        enabled: Callable[[], bool] | None = None,
        skip_empty_url: bool = False,
        strip_url: bool = False,
        suppress_errors: bool = True,
        on_error: Callable[[Exception], None] | None = None,
    ) -> None:
        self._url = url
        self._kwargs = dict(kwargs or {})
        self._enabled = enabled or (lambda: True)
        self._skip_empty_url = skip_empty_url
        self._strip_url = strip_url
        self._suppress_errors = suppress_errors
        self._on_error = on_error
        self._client: Any | None = None
        self._lock = threading.Lock()

    def _resolve_url(self) -> str:
        value = self._url() if callable(self._url) else self._url
        resolved = str(value or "")
        return resolved.strip() if self._strip_url else resolved

    def get(self) -> Any | None:
        if self._client is not None:
            return self._client
        if not self._enabled():
            return None

        url = self._resolve_url()
        if self._skip_empty_url and not url:
            return None

        with self._lock:
            if self._client is not None:
                return self._client
            if not self._enabled():
                return None

            url = self._resolve_url()
            if self._skip_empty_url and not url:
                return None

            try:
                import redis

                self._client = redis.Redis.from_url(url, **self._kwargs)
            except Exception as exc:
                if self._on_error is not None:
                    self._on_error(exc)
                if not self._suppress_errors:
                    raise
                self._client = None
            return self._client

    def invalidate(self) -> None:
        with self._lock:
            self._client = None
