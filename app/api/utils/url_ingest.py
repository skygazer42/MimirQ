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
import re
import socket
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlparse

import aiofiles
import httpx
from fastapi import HTTPException

from app.core.config import settings
from app.core.http_client import get_http_client_pool

_ALL_INTERFACES_HOST = str(ipaddress.IPv4Address(0))
_BLOCKED_HOSTS = {
    "localhost",
    "localhost.localdomain",
    _ALL_INTERFACES_HOST,
    "127.0.0.1",
    "::1",
}

_HEADER_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9\\-]{0,49}$")
_BLOCKED_EXTRA_HEADERS = {
    "host",
    "connection",
    "content-length",
    "transfer-encoding",
    "proxy-connection",
    "proxy-authorization",
}
_MAX_HEADER_VALUE_CHARS = 20_000

_URL_HOST_NOT_ALLOWED_DETAIL = "url host is not allowed"
_URL_HOST_RESOLUTION_FAILED_DETAIL = "failed to resolve url host"


def _sanitize_extra_headers(extra: dict[str, str] | None) -> dict[str, str]:
    """
    Best-effort header allowlist for URL ingestion/crawling.

    This is intentionally conservative to avoid request smuggling / SSRF bypass footguns.
    """
    if not extra or not isinstance(extra, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in extra.items():
        if not isinstance(k, str):
            continue
        name = k.strip()
        if not name:
            continue
        if not _HEADER_NAME_RE.match(name):
            continue
        if name.lower() in _BLOCKED_EXTRA_HEADERS:
            continue
        val = str(v or "")
        if len(val) > _MAX_HEADER_VALUE_CHARS:
            val = val[:_MAX_HEADER_VALUE_CHARS]
        out[name] = val
    return out


def _parse_csv(raw: str) -> list[str]:
    parts = [p.strip() for p in str(raw or "").split(",")]
    return [p for p in parts if p]


def _host_in_allowlist(host: str, allowlist: list[str]) -> bool:
    """
    Match host against an allowlist with optional wildcard suffix patterns.

    - "example.com" matches exactly.
    - "*.foo.com" matches "a.foo.com" but NOT "foo.com".
    """
    h = (host or "").strip().lower()
    if not h:
        return False
    for raw in allowlist:
        pat = (raw or "").strip().lower()
        if not pat:
            continue
        if pat.startswith("*.") and len(pat) > 2:
            suffix = pat[2:]
            if h == suffix:
                continue
            if h.endswith("." + suffix):
                return True
            continue
        if h == pat:
            return True
    return False


def _parse_allowed_ports(raw: str) -> list[int]:
    ports: list[int] = []
    for item in _parse_csv(raw):
        try:
            p = int(item)
        except Exception as exc:  # noqa: BLE001
            raise ValueError("invalid_port_allowlist") from exc
        if p <= 0 or p > 65535:
            raise ValueError("invalid_port_allowlist")
        if p not in ports:
            ports.append(p)
    return ports


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
        raise HTTPException(status_code=400, detail=_URL_HOST_NOT_ALLOWED_DETAIL)

    port = parsed.port or (443 if scheme == "https" else 80)

    # Optional host allowlist (defense-in-depth; useful for enterprise deployments).
    allowed_hosts = _parse_csv(str(getattr(settings, "URL_INGEST_ALLOWED_HOSTS", "") or ""))
    if allowed_hosts and not _host_in_allowlist(host, allowed_hosts):
        raise HTTPException(status_code=400, detail=_URL_HOST_NOT_ALLOWED_DETAIL)

    # Optional port allowlist.
    allowed_ports_raw = str(getattr(settings, "URL_INGEST_ALLOWED_PORTS", "") or "")
    if allowed_ports_raw.strip():
        try:
            allowed_ports = _parse_allowed_ports(allowed_ports_raw)
        except ValueError as exc:
            # Misconfiguration should fail closed (server-side error).
            raise HTTPException(status_code=500, detail="url ingest port allowlist misconfigured") from exc
        if port not in allowed_ports:
            raise HTTPException(status_code=400, detail="url port is not allowed")

    allow_private = bool(getattr(settings, "URL_INGEST_ALLOW_PRIVATE_IPS", False))

    # IP literal?
    is_ip_literal = False
    with contextlib.suppress(ValueError):
        ip = ipaddress.ip_address(host)
        is_ip_literal = True
        if not _is_allowed_ip(ip, allow_private=allow_private):
            raise HTTPException(status_code=400, detail=_URL_HOST_NOT_ALLOWED_DETAIL)

    if not is_ip_literal:
        # Resolve DNS (blocking -> thread).
        # Port already resolved/validated above.

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
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=400, detail=_URL_HOST_RESOLUTION_FAILED_DETAIL) from exc

        if not ips:
            raise HTTPException(status_code=400, detail=_URL_HOST_RESOLUTION_FAILED_DETAIL)

        for ip_str in ips:
            try:
                ip = ipaddress.ip_address(ip_str)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=_URL_HOST_RESOLUTION_FAILED_DETAIL) from exc
            if not _is_allowed_ip(ip, allow_private=allow_private):
                raise HTTPException(status_code=400, detail=_URL_HOST_NOT_ALLOWED_DETAIL)

    return raw


@dataclass(frozen=True)
class DownloadedURL:
    size_bytes: int
    content_type: str | None
    final_url: str
    # Best-effort HTTP origin metadata (used by connector staleness checks).
    last_modified: str | None = None
    etag: str | None = None


async def download_url_to_path(
    url: str,
    destination: Path,
    *,
    max_bytes: int | None = None,
    timeout_sec: float | None = None,
    follow_redirects: bool | None = None,
    user_agent: str | None = None,
    extra_headers: dict[str, str] | None = None,
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
    headers.update(_sanitize_extra_headers(extra_headers))

    destination.parent.mkdir(parents=True, exist_ok=True)
    size = 0
    pool = get_http_client_pool()
    # Security/compliance: do not propagate internal tenant/user headers to arbitrary URLs.
    client = await pool.get_external_client()

    # Validate the starting URL.
    current = await validate_url_for_ingest(url)
    max_redirects = int(getattr(settings, "URL_INGEST_MAX_REDIRECTS", 5) or 5)
    max_redirects = max(0, min(max_redirects, 20))

    try:
        hops = 0
        while True:
            async with client.stream(
                "GET",
                current,
                headers=headers,
                timeout=httpx.Timeout(timeout_eff),
                follow_redirects=False,  # validate per-hop ourselves
            ) as resp:
                # Manual redirect handling (defense-in-depth; prevents redirect-to-private SSRF).
                if resp.status_code in {301, 302, 303, 307, 308}:
                    if not follow_eff:
                        raise HTTPException(status_code=400, detail="redirects are not allowed")
                    if hops >= max_redirects:
                        raise HTTPException(status_code=400, detail="too many redirects")
                    loc = (resp.headers.get("location") or "").strip()
                    if not loc:
                        raise HTTPException(status_code=400, detail="redirect location missing")
                    nxt = urljoin(str(resp.url), loc)
                    current = await validate_url_for_ingest(nxt)
                    hops += 1
                    continue

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

                last_modified = (resp.headers.get("last-modified") or "").strip() or None
                etag = (resp.headers.get("etag") or "").strip() or None
                if etag and len(etag) > 500:
                    etag = etag[:500]

                return DownloadedURL(
                    size_bytes=int(size),
                    content_type=resp.headers.get("content-type"),
                    final_url=str(resp.url),
                    last_modified=last_modified,
                    etag=etag,
                )
    except HTTPException:
        with contextlib.suppress(OSError):
            destination.unlink(missing_ok=True)
        raise
    except Exception as exc:  # noqa: BLE001
        with contextlib.suppress(OSError):
            destination.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"failed to fetch url: {str(exc)[:120]}") from exc
