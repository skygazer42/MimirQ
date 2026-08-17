"""
Global HTTP client pool (sync + async).
Provides unified httpx client configs for external API calls.
"""

import asyncio
import contextlib
import logging
import threading
from typing import Any

import h2  # noqa: F401
import httpx

from app.core.config import settings
from app.core.http_env import httpx_trust_env
from app.core.logging_config import get_request_context
from app.core.secure_random import secure_jitter

logger = logging.getLogger("http_client")
_HTTP2_AVAILABLE = True


class HTTPClientPool:
    """Global HTTP client pool with connection reuse and concurrency control."""

    def __init__(self):
        self._async_client: httpx.AsyncClient | None = None
        self._async_client_external: httpx.AsyncClient | None = None
        self._sync_client: httpx.Client | None = None
        self._sync_client_external: httpx.Client | None = None
        self._async_lock = threading.Lock()
        self._sync_lock = threading.Lock()
        # Preserve legacy lock usage for code that expects async locking semantics.
        self._request_lock = asyncio.Lock()

    def _inject_internal_context_headers(self, request: httpx.Request) -> None:
        """
        Best-effort propagation of request-scoped context headers.

        - X-Request-ID: trace correlation
        - X-Tenant-ID (and optionally TENANT_HEADER) / X-User-ID: internal multi-tenant attribution
        """
        try:
            ctx = get_request_context()
        except Exception:  # noqa: BLE001
            return

        rid = (ctx.get("request_id") or "").strip()
        tenant_id = (ctx.get("tenant_id") or "").strip()
        user_id = (ctx.get("user_id") or "").strip()

        if rid and "X-Request-ID" not in request.headers:
            request.headers["X-Request-ID"] = rid
        tenant_header = str(getattr(settings, "TENANT_HEADER", "") or "X-Tenant-ID").strip() or "X-Tenant-ID"
        if tenant_id and tenant_header not in request.headers:
            request.headers[tenant_header] = tenant_id
        if tenant_id and tenant_header.lower() != "x-tenant-id" and "X-Tenant-ID" not in request.headers:
            request.headers["X-Tenant-ID"] = tenant_id
        if user_id and "X-User-ID" not in request.headers:
            request.headers["X-User-ID"] = user_id

    def _inject_external_context_headers(self, request: httpx.Request) -> None:
        """
        Best-effort propagation of request context to *external* third-party services.

        Security/Compliance:
        - Do NOT propagate internal attribution headers like X-Tenant-ID / X-User-ID.
        - Only X-Request-ID is included (when available) for correlation.
        """
        try:
            ctx = get_request_context()
        except Exception:  # noqa: BLE001
            return

        rid = (ctx.get("request_id") or "").strip()
        if rid and "X-Request-ID" not in request.headers:
            request.headers["X-Request-ID"] = rid

    async def _ainject_internal_context_headers(self, request: httpx.Request) -> None:
        """Async-compatible wrapper for internal request hooks."""
        await asyncio.sleep(0)
        self._inject_internal_context_headers(request)

    async def _ainject_external_context_headers(self, request: httpx.Request) -> None:
        """Async-compatible wrapper for external request hooks."""
        await asyncio.sleep(0)
        self._inject_external_context_headers(request)

    # Backwards-compatible name (internal behavior).
    def _inject_request_context_headers(self, request: httpx.Request) -> None:
        self._inject_internal_context_headers(request)

    def _build_limits(self) -> httpx.Limits:
        return httpx.Limits(
            max_connections=int(getattr(settings, "HTTP_CLIENT_MAX_CONNECTIONS", 100)),
            max_keepalive_connections=int(getattr(settings, "HTTP_CLIENT_MAX_KEEPALIVE_CONNECTIONS", 20)),
            keepalive_expiry=float(getattr(settings, "HTTP_CLIENT_KEEPALIVE_EXPIRY_SEC", 30.0)),
        )

    def _build_timeout(self) -> httpx.Timeout:
        return httpx.Timeout(
            connect=float(getattr(settings, "HTTP_CLIENT_TIMEOUT_CONNECT_SEC", 10.0)),
            read=float(getattr(settings, "HTTP_CLIENT_TIMEOUT_READ_SEC", 60.0)),
            write=float(getattr(settings, "HTTP_CLIENT_TIMEOUT_WRITE_SEC", 30.0)),
            pool=float(getattr(settings, "HTTP_CLIENT_TIMEOUT_POOL_SEC", 5.0)),
        )

    def _build_http2(self) -> bool:
        return bool(getattr(settings, "HTTP_CLIENT_HTTP2_ENABLED", True)) and _HTTP2_AVAILABLE

    def _build_trust_env(self) -> bool:
        return httpx_trust_env(logger=logger)

    def get_async_client(self) -> httpx.AsyncClient:
        """Get the global async HTTP client (lazy init)."""
        client = self._async_client
        if client is not None:
            return client

        with self._async_lock:
            client = self._async_client
            if client is not None:
                return client

            limits = self._build_limits()
            timeout = self._build_timeout()
            http2 = self._build_http2()
            trust_env = self._build_trust_env()

            self._async_client = httpx.AsyncClient(
                limits=limits,
                timeout=timeout,
                follow_redirects=True,
                http2=http2,
                trust_env=trust_env,
                event_hooks={"request": [self._ainject_internal_context_headers]},
            )
            logger.info(
                "HTTP async client pool initialized max_connections=%s http2=%s trust_env=%s",
                limits.max_connections,
                http2,
                trust_env,
            )
            return self._async_client

    def get_external_async_client(self) -> httpx.AsyncClient:
        """Get a pooled async HTTP client intended for third-party endpoints."""
        client = self._async_client_external
        if client is not None:
            return client

        with self._async_lock:
            client = self._async_client_external
            if client is not None:
                return client

            limits = self._build_limits()
            timeout = self._build_timeout()
            http2 = self._build_http2()
            trust_env = self._build_trust_env()

            self._async_client_external = httpx.AsyncClient(
                limits=limits,
                timeout=timeout,
                follow_redirects=True,
                http2=http2,
                trust_env=trust_env,
                event_hooks={"request": [self._ainject_external_context_headers]},
            )
            logger.info(
                "HTTP external async client initialized max_connections=%s http2=%s trust_env=%s",
                limits.max_connections,
                http2,
                trust_env,
            )
            return self._async_client_external

    def get_sync_client(self) -> httpx.Client:
        """Get the global sync HTTP client (lazy init)."""
        client = self._sync_client
        if client is not None:
            return client

        with self._sync_lock:
            client = self._sync_client
            if client is not None:
                return client

            limits = self._build_limits()
            timeout = self._build_timeout()
            http2 = self._build_http2()
            trust_env = self._build_trust_env()

            self._sync_client = httpx.Client(
                limits=limits,
                timeout=timeout,
                follow_redirects=True,
                http2=http2,
                trust_env=trust_env,
                event_hooks={"request": [self._inject_internal_context_headers]},
            )
            logger.info(
                "HTTP sync client pool initialized max_connections=%s http2=%s trust_env=%s",
                limits.max_connections,
                http2,
                trust_env,
            )
            return self._sync_client

    def get_external_sync_client(self) -> httpx.Client:
        """Get a pooled sync HTTP client intended for third-party endpoints."""
        client = self._sync_client_external
        if client is not None:
            return client

        with self._sync_lock:
            client = self._sync_client_external
            if client is not None:
                return client

            limits = self._build_limits()
            timeout = self._build_timeout()
            http2 = self._build_http2()
            trust_env = self._build_trust_env()

            self._sync_client_external = httpx.Client(
                limits=limits,
                timeout=timeout,
                follow_redirects=True,
                http2=http2,
                trust_env=trust_env,
                event_hooks={"request": [self._inject_external_context_headers]},
            )
            logger.info(
                "HTTP external sync client initialized max_connections=%s http2=%s trust_env=%s",
                limits.max_connections,
                http2,
                trust_env,
            )
            return self._sync_client_external

    async def get_client(self) -> httpx.AsyncClient:
        """Get the global async HTTP client (lazy init)."""
        # Keep the method async for backward compatibility (tests, callers),
        # but initialization is synchronous.
        await asyncio.sleep(0)
        return self.get_async_client()

    async def get_external_client(self) -> httpx.AsyncClient:
        """Async wrapper for the pooled external HTTP client."""
        await asyncio.sleep(0)
        return self.get_external_async_client()

    async def close(self):
        """Close the client pool."""
        async_client: httpx.AsyncClient | None
        sync_client: httpx.Client | None
        async_client_external: httpx.AsyncClient | None
        sync_client_external: httpx.Client | None
        with self._async_lock:
            async_client = self._async_client
            self._async_client = None
            async_client_external = self._async_client_external
            self._async_client_external = None
        with self._sync_lock:
            sync_client = self._sync_client
            self._sync_client = None
            sync_client_external = self._sync_client_external
            self._sync_client_external = None

        if sync_client is not None:
            try:
                sync_client.close()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to close HTTP sync client pool: %s", str(exc)[:200])

        if async_client is not None:
            try:
                await async_client.aclose()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to close HTTP async client pool: %s", str(exc)[:200])

        if sync_client_external is not None:
            try:
                sync_client_external.close()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to close HTTP external sync client: %s", str(exc)[:200])

        if async_client_external is not None:
            try:
                await async_client_external.aclose()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to close HTTP external async client: %s", str(exc)[:200])

        logger.info("HTTP client pool closed")

    async def request_with_retry(
        self,
        method: str,
        url: str,
        *,
        max_retries: int | None = None,
        retry_delay: float | None = None,
        backoff_factor: float | None = None,
        jitter: float | None = None,
        use_external_client: bool = False,
        **kwargs: Any,
    ) -> httpx.Response:
        """
        Send an HTTP request with automatic retries.

        Args:
            method: HTTP method (GET, POST, etc.).
            url: Request URL.
            max_retries: Max retry attempts.
            retry_delay: Initial retry delay (seconds).
            backoff_factor: Backoff factor (multiplies delay each retry).
            **kwargs: Additional httpx.request args.

        Returns:
            HTTP response.

        Raises:
            httpx.HTTPError: Request failure.
        """
        client = await (self.get_external_client() if use_external_client else self.get_client())
        last_exception = None

        max_retries = int(
            max_retries if max_retries is not None else getattr(settings, "HTTP_CLIENT_RETRY_MAX_RETRIES", 3)
        )
        retry_delay = float(
            retry_delay if retry_delay is not None else getattr(settings, "HTTP_CLIENT_RETRY_INITIAL_DELAY_SEC", 1.0)
        )
        backoff_factor = float(
            backoff_factor if backoff_factor is not None else getattr(settings, "HTTP_CLIENT_RETRY_BACKOFF_FACTOR", 2.0)
        )
        jitter = float(jitter if jitter is not None else getattr(settings, "HTTP_CLIENT_RETRY_JITTER_SEC", 0.0))

        current_delay = retry_delay

        for attempt in range(max_retries + 1):
            try:
                response = await client.request(method, url, **kwargs)
                response.raise_for_status()
                return response

            except (httpx.TimeoutException, httpx.NetworkError) as e:
                last_exception = e
                if attempt < max_retries:
                    sleep_for = current_delay + secure_jitter(jitter)
                    logger.warning(
                        "Request failed (attempt %s/%s): %s. Retrying in %.2fs...",
                        attempt + 1,
                        max_retries + 1,
                        str(e)[:200],
                        sleep_for,
                    )
                    await asyncio.sleep(sleep_for)
                    current_delay *= backoff_factor
                else:
                    logger.exception("Request failed after %s attempts: %s", max_retries + 1, str(e)[:200])

            except httpx.HTTPStatusError as e:
                # Retry on 5xx/429; raise other 4xx errors.
                status = int(getattr(e.response, "status_code", 0) or 0)
                retryable = status >= 500 or status == 429
                if retryable and attempt < max_retries:
                    last_exception = e
                    # Ensure the connection is released before sleeping/retrying.
                    with contextlib.suppress(Exception):
                        await e.response.aclose()
                    retry_after = None
                    if status == 429:
                        try:
                            retry_after = float(e.response.headers.get("Retry-After", ""))
                        except (TypeError, ValueError):
                            retry_after = None

                    base_delay = max(current_delay, retry_after) if retry_after else current_delay
                    sleep_for = base_delay + secure_jitter(jitter)
                    logger.warning(
                        "HTTP %s (attempt %s/%s). Retrying in %.2fs...",
                        status,
                        attempt + 1,
                        max_retries + 1,
                        sleep_for,
                    )
                    await asyncio.sleep(sleep_for)
                    current_delay *= backoff_factor
                else:
                    # Release connection for non-retryable errors too.
                    with contextlib.suppress(Exception):
                        await e.response.aclose()
                    raise

        # All retries failed.
        if last_exception:
            raise last_exception

        # Should not reach here.
        raise RuntimeError("Unexpected error in request_with_retry")

    async def get(self, url: str, **kwargs) -> httpx.Response:
        """GET request (with retry)."""
        return await self.request_with_retry("GET", url, **kwargs)

    async def post(self, url: str, **kwargs) -> httpx.Response:
        """POST request (with retry)."""
        return await self.request_with_retry("POST", url, **kwargs)

    async def put(self, url: str, **kwargs) -> httpx.Response:
        """PUT request (with retry)."""
        return await self.request_with_retry("PUT", url, **kwargs)

    async def delete(self, url: str, **kwargs) -> httpx.Response:
        """DELETE request (with retry)."""
        return await self.request_with_retry("DELETE", url, **kwargs)


# Global singleton.
_http_client_pool: HTTPClientPool | None = None


def get_http_client_pool() -> HTTPClientPool:
    """Get the global HTTP client pool instance."""
    global _http_client_pool
    if _http_client_pool is None:
        _http_client_pool = HTTPClientPool()
    return _http_client_pool


async def close_http_client_pool():
    """Close the global HTTP client pool."""
    global _http_client_pool
    if _http_client_pool is not None:
        await _http_client_pool.close()
        _http_client_pool = None


__all__ = [
    "HTTPClientPool",
    "get_http_client_pool",
    "close_http_client_pool",
]
