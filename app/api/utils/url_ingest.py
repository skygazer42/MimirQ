"""
URL ingestion helpers (connector skeleton).

This module is intentionally conservative to reduce SSRF risk:
- Only http/https
- Block private/loopback/link-local by default (configurable)
- Redirect following disabled by default (configurable)
- Streaming download with hard size limit
"""


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
_REDIRECT_STATUS_CODES = {301, 302, 303, 307, 308}


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


@dataclass(frozen=True)
class _ParsedIngestURL:
    raw: str
    host: str
    port: int


def _parse_ingest_url(url: str) -> _ParsedIngestURL:
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
    try:
        port = parsed.port or (443 if scheme == "https" else 80)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="url port is not allowed") from exc
    return _ParsedIngestURL(raw=raw, host=host, port=port)


def _validate_blocked_host(host: str) -> None:
    if host in _BLOCKED_HOSTS or host.endswith(".local"):
        raise HTTPException(status_code=400, detail=_URL_HOST_NOT_ALLOWED_DETAIL)


def _validate_host_allowlist(host: str) -> None:
    allowed_hosts = _parse_csv(str(getattr(settings, "URL_INGEST_ALLOWED_HOSTS", "") or ""))
    if allowed_hosts and not _host_in_allowlist(host, allowed_hosts):
        raise HTTPException(status_code=400, detail=_URL_HOST_NOT_ALLOWED_DETAIL)


def _validate_port_allowlist(port: int) -> None:
    allowed_ports_raw = str(getattr(settings, "URL_INGEST_ALLOWED_PORTS", "") or "")
    if not allowed_ports_raw.strip():
        return
    try:
        allowed_ports = _parse_allowed_ports(allowed_ports_raw)
    except ValueError as exc:
        # Misconfiguration should fail closed (server-side error).
        raise HTTPException(status_code=500, detail="url ingest port allowlist misconfigured") from exc
    if port not in allowed_ports:
        raise HTTPException(status_code=400, detail="url port is not allowed")


def _ip_literal_or_none(host: str) -> ipaddress._BaseAddress | None:  # type: ignore[name-defined]
    try:
        return ipaddress.ip_address(host)
    except ValueError:
        return None


def _validate_ip_allowed(ip: ipaddress._BaseAddress, *, allow_private: bool) -> None:  # type: ignore[name-defined]
    if not _is_allowed_ip(ip, allow_private=allow_private):
        raise HTTPException(status_code=400, detail=_URL_HOST_NOT_ALLOWED_DETAIL)


def _resolve_host_sync(host: str, port: int) -> list[str]:
    out: list[str] = []
    for fam, _, _, _, sockaddr in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM):
        if fam not in (socket.AF_INET, socket.AF_INET6):
            continue
        ip_str = sockaddr[0]
        if ip_str and ip_str not in out:
            out.append(ip_str)
    return out


async def _resolve_host_ips(host: str, port: int) -> list[str]:
    try:
        ips = await asyncio.to_thread(_resolve_host_sync, host, port)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=_URL_HOST_RESOLUTION_FAILED_DETAIL) from exc
    if not ips:
        raise HTTPException(status_code=400, detail=_URL_HOST_RESOLUTION_FAILED_DETAIL)
    return ips


def _validate_resolved_ips(ips: list[str], *, allow_private: bool) -> None:
    for ip_str in ips:
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=_URL_HOST_RESOLUTION_FAILED_DETAIL) from exc
        _validate_ip_allowed(ip, allow_private=allow_private)


async def validate_url_for_ingest(url: str) -> str:
    """
    Validate that a URL is safe-enough for server-side fetching (best-effort).

    Returns the normalized URL string on success.
    """
    parsed_url = _parse_ingest_url(url)
    _validate_blocked_host(parsed_url.host)
    _validate_host_allowlist(parsed_url.host)
    _validate_port_allowlist(parsed_url.port)
    allow_private = bool(getattr(settings, "URL_INGEST_ALLOW_PRIVATE_IPS", False))

    if ip := _ip_literal_or_none(parsed_url.host):
        _validate_ip_allowed(ip, allow_private=allow_private)
        return parsed_url.raw

    ips = await _resolve_host_ips(parsed_url.host, parsed_url.port)
    _validate_resolved_ips(ips, allow_private=allow_private)
    return parsed_url.raw


@dataclass(frozen=True)
class DownloadedURL:
    size_bytes: int
    content_type: str | None
    final_url: str
    # Best-effort HTTP origin metadata (used by connector staleness checks).
    last_modified: str | None = None
    etag: str | None = None


@dataclass(frozen=True)
class URLDownloadOptions:
    max_bytes: int | None = None
    timeout_sec: float | None = None
    follow_redirects: bool | None = None
    user_agent: str | None = None
    extra_headers: dict[str, str] | None = None


@dataclass(frozen=True)
class _DownloadOptions:
    max_bytes: int
    timeout_sec: float
    follow_redirects: bool
    headers: dict[str, str]
    max_redirects: int


def _effective_max_bytes(max_bytes: int | None) -> int:
    max_bytes_eff = int(max_bytes if max_bytes is not None else getattr(settings, "URL_INGEST_MAX_BYTES", 0) or 0)
    if max_bytes_eff <= 0:
        return int(getattr(settings, "MAX_FILE_SIZE", 0) or 50_000_000)
    return max_bytes_eff


def _build_download_headers(*, user_agent: str | None, extra_headers: dict[str, str] | None) -> dict[str, str]:
    ua = (user_agent or "").strip() or "MimirQ/1.0 (+url-ingest)"
    headers = {"Accept": "*/*", "User-Agent": ua}
    headers.update(_sanitize_extra_headers(extra_headers))
    return headers


def _download_options(options: URLDownloadOptions | None) -> _DownloadOptions:
    raw = options or URLDownloadOptions()
    max_redirects = int(getattr(settings, "URL_INGEST_MAX_REDIRECTS", 5) or 5)
    return _DownloadOptions(
        max_bytes=_effective_max_bytes(raw.max_bytes),
        timeout_sec=float(
            raw.timeout_sec if raw.timeout_sec is not None else getattr(settings, "URL_INGEST_TIMEOUT_SEC", 30.0)
        ),
        follow_redirects=(
            bool(raw.follow_redirects)
            if raw.follow_redirects is not None
            else bool(getattr(settings, "URL_INGEST_FOLLOW_REDIRECTS", False))
        ),
        headers=_build_download_headers(user_agent=raw.user_agent, extra_headers=raw.extra_headers),
        max_redirects=max(0, min(max_redirects, 20)),
    )


async def _validated_redirect_url(resp: httpx.Response, *, follow: bool, hops: int, max_redirects: int) -> str | None:
    if resp.status_code not in _REDIRECT_STATUS_CODES:
        return None
    if not follow:
        raise HTTPException(status_code=400, detail="redirects are not allowed")
    if hops >= max_redirects:
        raise HTTPException(status_code=400, detail="too many redirects")
    loc = (resp.headers.get("location") or "").strip()
    if not loc:
        raise HTTPException(status_code=400, detail="redirect location missing")
    return await validate_url_for_ingest(urljoin(str(resp.url), loc))


def _raise_for_fetch_status(resp: httpx.Response) -> None:
    if resp.status_code >= 400:
        raise HTTPException(status_code=400, detail=f"failed to fetch url (status={resp.status_code})")


def _enforce_content_length(resp: httpx.Response, *, max_bytes: int) -> None:
    content_length = resp.headers.get("content-length")
    if not content_length:
        return
    with contextlib.suppress(ValueError):
        if int(content_length) > max_bytes:
            raise HTTPException(status_code=413, detail="remote file too large")


async def _write_response_body(resp: httpx.Response, *, destination: Path, max_bytes: int) -> int:
    size = 0
    async with aiofiles.open(destination, "wb") as f:
        async for chunk in resp.aiter_bytes():
            if not chunk:
                continue
            size += len(chunk)
            if size > max_bytes:
                raise HTTPException(status_code=413, detail="remote file too large")
            await f.write(chunk)
    return size


def _download_result(resp: httpx.Response, *, size_bytes: int) -> DownloadedURL:
    last_modified = (resp.headers.get("last-modified") or "").strip() or None
    etag = (resp.headers.get("etag") or "").strip() or None
    if etag and len(etag) > 500:
        etag = etag[:500]
    return DownloadedURL(
        size_bytes=int(size_bytes),
        content_type=resp.headers.get("content-type"),
        final_url=str(resp.url),
        last_modified=last_modified,
        etag=etag,
    )


def _cleanup_partial_download(destination: Path) -> None:
    with contextlib.suppress(OSError):
        destination.unlink(missing_ok=True)


async def download_url_to_path(
    url: str,
    destination: Path,
    *,
    options: URLDownloadOptions | None = None,
) -> DownloadedURL:
    """
    Stream-download URL content to a local file with a hard size limit.
    """
    options = _download_options(options)
    destination.parent.mkdir(parents=True, exist_ok=True)
    pool = get_http_client_pool()
    # Security/compliance: do not propagate internal tenant/user headers to arbitrary URLs.
    client = await pool.get_external_client()

    current = await validate_url_for_ingest(url)

    try:
        hops = 0
        while True:
            async with client.stream(
                "GET",
                current,
                headers=options.headers,
                timeout=httpx.Timeout(options.timeout_sec),
                follow_redirects=False,  # validate per-hop ourselves
            ) as resp:
                # Manual redirect handling (defense-in-depth; prevents redirect-to-private SSRF).
                if redirect_url := await _validated_redirect_url(
                    resp,
                    follow=options.follow_redirects,
                    hops=hops,
                    max_redirects=options.max_redirects,
                ):
                    current = redirect_url
                    hops += 1
                    continue

                _raise_for_fetch_status(resp)
                _enforce_content_length(resp, max_bytes=options.max_bytes)
                size = await _write_response_body(resp, destination=destination, max_bytes=options.max_bytes)
                return _download_result(resp, size_bytes=size)
    except HTTPException:
        _cleanup_partial_download(destination)
        raise
    except Exception as exc:  # noqa: BLE001
        _cleanup_partial_download(destination)
        raise HTTPException(status_code=500, detail=f"failed to fetch url: {str(exc)[:120]}") from exc
