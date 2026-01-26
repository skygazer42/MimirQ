"""
URL ingestion helpers (connector skeleton).

This module is intentionally conservative to reduce SSRF risk:
- Only http/https
- Block private/loopback/link-local by default (configurable)
- Redirect following disabled by default (configurable)
- Streaming download with hard size limit
"""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import socket
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import aiofiles
import httpx
from fastapi import HTTPException

from app.core.config import settings
from app.core.http_client import get_http_client_pool


_BLOCKED_HOSTS = {
    "localhost",
    "localhost.localdomain",
    "0.0.0.0",
    "127.0.0.1",
    "::1",
}


def _is_allowed_ip(ip: ipaddress._BaseAddress, *, allow_private: bool) -> bool:  # type: ignore[name-defined]
    if allow_private:
        return True
    # `is_global` is the most practical "public routable" signal.
    return bool(getattr(ip, "is_global", False))


async def validate_url_for_ingest(url: str) -> str:
    """
    Validate that a URL is safe-enough for server-side fetching (best-effort).

    Returns the normalized URL string on success.
    """
    raw = (url or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="url is required")

    parsed = urlparse(raw)
    scheme = (parsed.scheme or "").lower().strip()
    if scheme not in {"http", "https"}:
        raise HTTPException(status_code=400, detail="url scheme must be http or https")
    if not parsed.hostname:
        raise HTTPException(status_code=400, detail="url hostname is required")

    host = parsed.hostname.strip().lower()
    if host in _BLOCKED_HOSTS or host.endswith(".local"):
        raise HTTPException(status_code=400, detail="url host is not allowed")

    allow_private = bool(getattr(settings, "URL_INGEST_ALLOW_PRIVATE_IPS", False))

    # IP literal?
    with contextlib.suppress(ValueError):
        ip = ipaddress.ip_address(host)
        if not _is_allowed_ip(ip, allow_private=allow_private):
            raise HTTPException(status_code=400, detail="url host is not allowed")
        return raw

    # Resolve DNS (blocking -> thread).
    port = parsed.port or (443 if scheme == "https" else 80)

    def _resolve() -> list[str]:
        out: list[str] = []
        for fam, _, _, _, sockaddr in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM):
            if fam not in (socket.AF_INET, socket.AF_INET6):
                continue
            ip_str = sockaddr[0]
            if ip_str and ip_str not in out:
                out.append(ip_str)
        return out

    try:
        ips = await asyncio.to_thread(_resolve)
    except Exception:
        raise HTTPException(status_code=400, detail="failed to resolve url host")

    if not ips:
        raise HTTPException(status_code=400, detail="failed to resolve url host")

    for ip_str in ips:
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            raise HTTPException(status_code=400, detail="failed to resolve url host")
        if not _is_allowed_ip(ip, allow_private=allow_private):
            raise HTTPException(status_code=400, detail="url host is not allowed")

    return raw


@dataclass(frozen=True)
class DownloadedURL:
    size_bytes: int
    content_type: str | None
    final_url: str


async def download_url_to_path(
    url: str,
    destination: Path,
    *,
    max_bytes: int | None = None,
    timeout_sec: float | None = None,
    follow_redirects: bool | None = None,
    user_agent: str | None = None,
) -> DownloadedURL:
    """
    Stream-download URL content to a local file with a hard size limit.
    """
    max_bytes_eff = int(max_bytes if max_bytes is not None else getattr(settings, "URL_INGEST_MAX_BYTES", 0) or 0)
    if max_bytes_eff <= 0:
        max_bytes_eff = int(getattr(settings, "MAX_FILE_SIZE", 0) or 50_000_000)

    timeout_eff = float(timeout_sec if timeout_sec is not None else getattr(settings, "URL_INGEST_TIMEOUT_SEC", 30.0))
    follow_eff = bool(follow_redirects) if follow_redirects is not None else bool(getattr(settings, "URL_INGEST_FOLLOW_REDIRECTS", False))

    headers: dict[str, str] = {
        "Accept": "*/*",
    }
    ua = (user_agent or "").strip()
    if not ua:
        ua = "MimirQ/1.0 (+url-ingest)"
    headers["User-Agent"] = ua

    destination.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    pool = get_http_client_pool()
    client = await pool.get_client()

    try:
        async with client.stream(
            "GET",
            url,
            headers=headers,
            timeout=httpx.Timeout(timeout_eff),
            follow_redirects=follow_eff,
        ) as resp:
            if resp.status_code >= 400:
                raise HTTPException(status_code=400, detail=f"failed to fetch url (status={resp.status_code})")

            content_length = resp.headers.get("content-length")
            if content_length:
                with contextlib.suppress(Exception):
                    if int(content_length) > max_bytes_eff:
                        raise HTTPException(status_code=413, detail="remote file too large")

            async with aiofiles.open(destination, "wb") as f:
                async for chunk in resp.aiter_bytes():
                    if not chunk:
                        continue
                    size += len(chunk)
                    if size > max_bytes_eff:
                        raise HTTPException(status_code=413, detail="remote file too large")
                    await f.write(chunk)

            return DownloadedURL(
                size_bytes=int(size),
                content_type=resp.headers.get("content-type"),
                final_url=str(resp.url),
            )
    except HTTPException:
        with contextlib.suppress(OSError):
            destination.unlink(missing_ok=True)
        raise
    except Exception as exc:  # noqa: BLE001
        with contextlib.suppress(OSError):
            destination.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"failed to fetch url: {str(exc)[:120]}") from exc

