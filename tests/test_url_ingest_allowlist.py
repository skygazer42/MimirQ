from __future__ import annotations

import socket
from pathlib import Path

import httpx
import pytest
from fastapi import HTTPException

from app.core.config import settings
from tests.helpers.async_utils import yield_control


def _fake_getaddrinfo_global(host: str, port: int, *args, **kwargs):  # noqa: ANN001
    # Return a public IPv4 address for deterministic tests (no real DNS).
    return [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", int(port))),
    ]


@pytest.mark.asyncio
async def test_validate_url_for_ingest_enforces_host_allowlist(monkeypatch: pytest.MonkeyPatch):
    from app.api.utils.url_ingest import validate_url_for_ingest

    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo_global, raising=True)
    monkeypatch.setattr(settings, "URL_INGEST_ALLOWED_HOSTS", "example.com,*.foo.com", raising=False)
    monkeypatch.setattr(settings, "URL_INGEST_ALLOWED_PORTS", "", raising=False)
    monkeypatch.setattr(settings, "URL_INGEST_ALLOW_PRIVATE_IPS", False, raising=False)

    assert await validate_url_for_ingest("https://example.com/a") == "https://example.com/a"
    assert await validate_url_for_ingest("https://a.foo.com/x") == "https://a.foo.com/x"

    # Wildcard suffix should not match apex.
    with pytest.raises(HTTPException) as exc:
        await validate_url_for_ingest("https://foo.com/x")
    assert exc.value.status_code == 400

    # Not in allowlist.
    with pytest.raises(HTTPException) as exc2:
        await validate_url_for_ingest("https://bar.com/x")
    assert exc2.value.status_code == 400


@pytest.mark.asyncio
async def test_validate_url_for_ingest_enforces_port_allowlist(monkeypatch: pytest.MonkeyPatch):
    from app.api.utils.url_ingest import validate_url_for_ingest

    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo_global, raising=True)
    monkeypatch.setattr(settings, "URL_INGEST_ALLOWED_HOSTS", "example.com", raising=False)
    monkeypatch.setattr(settings, "URL_INGEST_ALLOWED_PORTS", "443", raising=False)

    assert await validate_url_for_ingest("https://example.com/a") == "https://example.com/a"

    with pytest.raises(HTTPException) as exc:
        await validate_url_for_ingest("http://example.com/a")
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_validate_url_for_ingest_port_allowlist_misconfig_fails_closed(monkeypatch: pytest.MonkeyPatch):
    from app.api.utils.url_ingest import validate_url_for_ingest

    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo_global, raising=True)
    monkeypatch.setattr(settings, "URL_INGEST_ALLOWED_HOSTS", "example.com", raising=False)
    monkeypatch.setattr(settings, "URL_INGEST_ALLOWED_PORTS", "oops", raising=False)

    with pytest.raises(HTTPException) as exc:
        await validate_url_for_ingest("https://example.com/a")
    assert exc.value.status_code == 500


@pytest.mark.asyncio
async def test_download_url_to_path_validates_redirect_hops(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from app.api.utils import url_ingest as url_ingest_module

    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        host = request.url.host
        if host == "allowed.com":
            return httpx.Response(302, headers={"location": "https://blocked.com/file.txt"})
        if host == "blocked.com":
            return httpx.Response(200, content=b"should-not-fetch", headers={"content-type": "text/plain"})
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)

    class _Pool:
        async def get_external_client(self):  # noqa: ANN202
            await yield_control()
            return client

    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo_global, raising=True)
    monkeypatch.setattr(settings, "URL_INGEST_ALLOWED_HOSTS", "allowed.com", raising=False)
    monkeypatch.setattr(settings, "URL_INGEST_ALLOWED_PORTS", "", raising=False)
    monkeypatch.setattr(settings, "URL_INGEST_MAX_REDIRECTS", 2, raising=False)
    monkeypatch.setattr(url_ingest_module, "get_http_client_pool", lambda: _Pool(), raising=True)

    dest = tmp_path / "out.bin"
    with pytest.raises(HTTPException) as exc:
        await url_ingest_module.download_url_to_path(
            "https://allowed.com/start",
            dest,
            options=url_ingest_module.URLDownloadOptions(
                follow_redirects=True,
                timeout_sec=5.0,
                max_bytes=1024,
            ),
        )
    assert exc.value.status_code == 400
    assert calls and calls[0].startswith("https://allowed.com/")
    # Must not request the blocked host if validation is enforced per hop.
    assert not any("blocked.com" in c for c in calls)
    assert not dest.exists()

    await client.aclose()


@pytest.mark.asyncio
async def test_download_url_to_path_rejects_large_content_length(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    from app.api.utils import url_ingest as url_ingest_module

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not-read", headers={"content-length": "2048"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    class _Pool:
        async def get_external_client(self):  # noqa: ANN202
            await yield_control()
            return client

    monkeypatch.setattr(socket, "getaddrinfo", _fake_getaddrinfo_global, raising=True)
    monkeypatch.setattr(settings, "URL_INGEST_ALLOWED_HOSTS", "example.com", raising=False)
    monkeypatch.setattr(settings, "URL_INGEST_ALLOWED_PORTS", "", raising=False)
    monkeypatch.setattr(url_ingest_module, "get_http_client_pool", lambda: _Pool(), raising=True)

    dest = tmp_path / "out.bin"
    with pytest.raises(HTTPException) as exc:
        await url_ingest_module.download_url_to_path(
            "https://example.com/file.txt",
            dest,
            options=url_ingest_module.URLDownloadOptions(max_bytes=1024),
        )
    assert exc.value.status_code == 413
    assert not dest.exists()

    await client.aclose()
