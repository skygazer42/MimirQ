"""校验外部网址，并在大小和超时限制内下载为本地文件。

供网址入库、网站采集和模型连接测试共用。连接使用已校验的 IP，
HTTP Host 和 TLS SNI 仍使用原域名。
"""

import asyncio
import ipaddress
import re
import socket
from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path
from urllib.parse import urljoin, urlparse

import anyio
import httpx
from fastapi import HTTPException

from app.api.utils.file_io import _close_transfer_resources, cleanup_partial_file
from app.core.config import settings

_BLOCKED_HOSTS = frozenset({"localhost", "localhost.localdomain", "0.0.0.0", "127.0.0.1", "::1"})
_HEADER_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,49}")
_BLOCKED_EXTRA_HEADERS = frozenset(
    {
        "host",
        "connection",
        "content-length",
        "transfer-encoding",
        "proxy-connection",
        "proxy-authorization",
    }
)
_MAX_HEADER_VALUE_CHARS = 20_000
_DEFAULT_USER_AGENT = "MimirQ/1.0 (+url-ingest)"
_SENSITIVE_REQUEST_HEADERS = frozenset({"authorization", "cookie", "proxy-authorization"})
_URL_HOST_NOT_ALLOWED_DETAIL = "url host is not allowed"
_REDIRECT_STATUS_CODES = frozenset(
    {
        HTTPStatus.MOVED_PERMANENTLY,
        HTTPStatus.FOUND,
        HTTPStatus.SEE_OTHER,
        HTTPStatus.TEMPORARY_REDIRECT,
        HTTPStatus.PERMANENT_REDIRECT,
    }
)


@dataclass(frozen=True)
class ValidatedFetchTarget:
    """保留原始网址与域名，connect_url 只将连接目标替换为已验证的 IP。"""

    raw: str
    connect_url: str
    host: str
    host_header: str


@dataclass(frozen=True)
class DownloadedURL:
    """下载结果及用于来源更新检查的 HTTP 元数据。"""

    size_bytes: int
    content_type: str | None
    final_url: str
    last_modified: str | None = None
    etag: str | None = None


async def validate_fetch_target(url: str, *, enforce_allowlists: bool = True) -> ValidatedFetchTarget:
    """依次检查网址、访问范围和所有 DNS 地址，返回固定连接目标。"""
    url = url.strip()
    try:
        parsed_url = urlparse(url)
        host = parsed_url.hostname
        port = parsed_url.port
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid URL") from exc

    scheme = parsed_url.scheme
    if scheme not in {"http", "https"} or not host or port == 0:
        raise HTTPException(status_code=400, detail="Invalid URL")
    if parsed_url.username is not None or parsed_url.password is not None:
        raise HTTPException(status_code=400, detail="url credentials are not allowed")

    try:
        host = _normalize_host(host.strip())
    except (httpx.InvalidURL, UnicodeEncodeError) as exc:
        raise HTTPException(status_code=400, detail="Invalid URL") from exc
    if port is None:
        port = 443 if scheme == "https" else 80

    if host in _BLOCKED_HOSTS or host.endswith(".local"):
        raise HTTPException(status_code=400, detail=_URL_HOST_NOT_ALLOWED_DETAIL)
    if enforce_allowlists:
        allowed_hosts = _parse_csv(settings.URL_INGEST_ALLOWED_HOSTS)
        if allowed_hosts and not _host_in_allowlist(host, allowed_hosts):
            raise HTTPException(status_code=400, detail=_URL_HOST_NOT_ALLOWED_DETAIL)
        _validate_port_allowlist(port)

    addresses = await _resolve_host_addresses(host, port)
    if not settings.URL_INGEST_ALLOW_PRIVATE_IPS and any(not address.is_global for address in addresses):
        raise HTTPException(status_code=400, detail=_URL_HOST_NOT_ALLOWED_DETAIL)

    # IPv6 在 URL 和 Host 头中需要方括号；HTTP 域名身份不能被连接 IP 替换。
    connect_host = str(addresses[0])
    connection_authority = f"[{connect_host}]:{port}" if ":" in connect_host else f"{connect_host}:{port}"
    host_header = f"[{host}]:{port}" if ":" in host else f"{host}:{port}"
    connect_url = parsed_url._replace(netloc=connection_authority).geturl()
    return ValidatedFetchTarget(raw=url, connect_url=connect_url, host=host, host_header=host_header)


async def validate_url_for_ingest(url: str) -> str:
    """验证网址与当前 DNS 结果，返回去除首尾空白的原始网址。"""
    target = await validate_fetch_target(url)
    return target.raw


def build_pinned_http_clients(
    target: ValidatedFetchTarget,
    *,
    trust_env: bool,
    timeout: httpx.Timeout | float,
) -> tuple[httpx.Client, httpx.AsyncClient]:
    """为模型连接测试固定 Host／SNI；调用方负责关闭两个客户端。"""

    def set_host_and_sni(request: httpx.Request) -> None:
        request.headers["Host"] = target.host_header
        request.extensions["sni_hostname"] = target.host

    async def set_host_and_sni_async(request: httpx.Request) -> None:
        set_host_and_sni(request)

    client_options = {"follow_redirects": False, "trust_env": trust_env, "timeout": timeout}
    return (
        httpx.Client(**client_options, event_hooks={"request": [set_host_and_sni]}),
        httpx.AsyncClient(**client_options, event_hooks={"request": [set_host_and_sni_async]}),
    )


async def download_url_to_path(
    target: ValidatedFetchTarget,
    destination: Path,
    *,
    max_bytes: int,
    timeout_sec: float,
    follow_redirects: bool,
    user_agent: str | None = None,
    extra_headers: dict[str, str] | None = None,
) -> DownloadedURL:
    """下载已验证的目标；大小和超时由调用方从已验证配置传入。"""
    request_headers = _build_request_headers(user_agent, extra_headers)
    redirects_remaining = max(0, min(settings.URL_INGEST_MAX_REDIRECTS, 20))
    try:
        await anyio.Path(destination.parent).mkdir(parents=True, exist_ok=True)

        while True:
            # 每跳使用独立客户端，防止不同域名复用同一 IP 上的 TLS 连接。
            async with (
                httpx.AsyncClient(http2=False, follow_redirects=False, trust_env=False) as client,
                client.stream(
                    "GET",
                    target.connect_url,
                    headers={**request_headers, "Host": target.host_header},
                    timeout=httpx.Timeout(timeout_sec),
                    extensions={"sni_hostname": target.host},
                ) as response,
            ):
                if response.status_code in _REDIRECT_STATUS_CODES:
                    redirect_url = _redirect_url(
                        response,
                        request_url=target.raw,
                        follow_redirects=follow_redirects,
                        redirects_remaining=redirects_remaining,
                    )
                else:
                    downloaded = await _save_download_response(
                        response, destination=destination, max_bytes=max_bytes, final_url=target.raw
                    )
                    break

            next_target = await validate_fetch_target(redirect_url)
            current_origin = (urlparse(target.raw).scheme, target.host_header)
            next_origin = (urlparse(next_target.raw).scheme, next_target.host_header)
            if current_origin != next_origin:
                # 凭据只属于原请求的协议、域名和端口。
                request_headers = {
                    name: value
                    for name, value in request_headers.items()
                    if name.lower() not in _SENSITIVE_REQUEST_HEADERS
                }
            target = next_target
            redirects_remaining -= 1

    except BaseException:
        # 包含取消；清理后继续抛出原异常，不能返回下载成功。
        await cleanup_partial_file(destination, operation="download")
        raise

    return downloaded


def _redirect_url(
    response: httpx.Response,
    *,
    request_url: str,
    follow_redirects: bool,
    redirects_remaining: int,
) -> str:
    if not follow_redirects:
        raise HTTPException(status_code=400, detail="redirects are not allowed")
    if redirects_remaining <= 0:
        raise HTTPException(status_code=400, detail="too many redirects")

    location = response.headers.get("location", "").strip()
    if not location:
        raise HTTPException(status_code=400, detail="redirect location missing")
    return urljoin(request_url, location)


async def _save_download_response(
    response: httpx.Response, *, destination: Path, max_bytes: int, final_url: str
) -> DownloadedURL:
    """检查远端响应，限量写入文件，再组装下载结果。"""
    if response.status_code >= 400:
        raise HTTPException(status_code=400, detail=f"failed to fetch url (status={response.status_code})")

    size_bytes = 0
    output = await anyio.open_file(destination, "wb")
    primary_error: BaseException | None = None
    try:
        async for chunk in response.aiter_bytes():
            size_bytes += len(chunk)
            if size_bytes > max_bytes:
                raise HTTPException(status_code=413, detail="remote file too large")
            await output.write(chunk)
    except BaseException as exc:  # noqa: BLE001 - Cancellation must also close the output.
        primary_error = exc

    primary_error = await _close_transfer_resources([("output", output.aclose)], primary_error=primary_error)
    if primary_error is not None:
        raise primary_error

    etag = response.headers.get("etag")
    if etag is not None:
        etag = etag[:500]
    return DownloadedURL(
        size_bytes=size_bytes,
        content_type=response.headers.get("content-type"),
        final_url=final_url,
        last_modified=response.headers.get("last-modified"),
        etag=etag,
    )


def _build_request_headers(user_agent: str | None, extra: dict[str, str] | None) -> dict[str, str]:
    """过滤不可覆盖的传输头，拒绝换行，限制外部请求头长度。"""
    headers = {"Accept": "*/*", "User-Agent": _DEFAULT_USER_AGENT}
    if user_agent is not None and user_agent.strip():
        headers["User-Agent"] = user_agent.strip()
    if extra is None:
        return headers
    for raw_name, value in extra.items():
        name = raw_name.strip()
        if not _HEADER_NAME_RE.fullmatch(name) or name.lower() in _BLOCKED_EXTRA_HEADERS:
            continue
        if "\r" in value or "\n" in value:
            raise HTTPException(status_code=400, detail="invalid fetch header value")
        headers[name] = value[:_MAX_HEADER_VALUE_CHARS]
    return headers


def _parse_csv(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def _normalize_host(host: str) -> str:
    """域名遵循 HTTPX 的 IDNA 规则；ASCII 和 IP 保留原有匹配语义。"""
    host = host.lower()
    if host.isascii():
        return host
    return httpx.URL(host=host).raw_host.decode("ascii")


def _host_in_allowlist(host: str, allowlist: list[str]) -> bool:
    """host 已规范化，规则已去空白；*.example.com 只匹配子域名。"""
    for pattern in allowlist:
        wildcard = pattern.startswith("*.") and len(pattern) > 2
        try:
            pattern = _normalize_host(pattern[2:] if wildcard else pattern)
        except (httpx.InvalidURL, UnicodeEncodeError) as exc:
            raise HTTPException(status_code=500, detail="url ingest host allowlist misconfigured") from exc
        if wildcard:
            if host.endswith(f".{pattern}"):
                return True
        elif host == pattern:
            return True
    return False


def _validate_port_allowlist(port: int) -> None:
    configured_ports = settings.URL_INGEST_ALLOWED_PORTS
    if not configured_ports.strip():
        return
    try:
        allowed_ports = {int(item) for item in _parse_csv(configured_ports)}
    except ValueError as exc:
        raise HTTPException(status_code=500, detail="url ingest port allowlist misconfigured") from exc
    if any(value < 1 or value > 65535 for value in allowed_ports):
        raise HTTPException(status_code=500, detail="url ingest port allowlist misconfigured")
    if port not in allowed_ports:
        raise HTTPException(status_code=400, detail="url port is not allowed")


async def _resolve_host_addresses(host: str, port: int) -> list[ipaddress.IPv4Address | ipaddress.IPv6Address]:
    """IP 直接解析以保留 IPv6 网卡标识；域名解析结果保序去重。"""
    try:
        return [ipaddress.ip_address(host)]
    except ValueError:
        pass

    resolved = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    resolved_ips = dict.fromkeys(sockaddr[0] for _, _, _, _, sockaddr in resolved)
    return [ipaddress.ip_address(address) for address in resolved_ips]
