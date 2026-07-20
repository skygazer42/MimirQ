import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path

import pytest
from fastapi import HTTPException
from starlette.types import Message, Scope

from app.api.middleware.body_size_limit import BodySizeLimitMiddleware
from app.api.utils import url_ingest


def _scope(headers: list[tuple[bytes, bytes]] | None = None) -> Scope:
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/upload",
        "raw_path": b"/upload",
        "query_string": b"",
        "root_path": "",
        "headers": headers or [],
        "client": ("127.0.0.1", 1234),
        "server": ("test", 80),
    }


def _run_body_limit(messages: list[Message], *, limit: int) -> tuple[bool, list[Message], bytes]:
    called = False
    sent: list[Message] = []
    received = bytearray()

    async def app(
        scope: Scope, receive: Callable[[], Awaitable[Message]], send: Callable[[Message], Awaitable[None]]
    ) -> None:
        nonlocal called
        called = True
        while True:
            message = await receive()
            received.extend(message.get("body", b""))
            if not message.get("more_body", False):
                break
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    queued = iter(messages)

    async def receive() -> Message:
        return next(queued)

    async def send(message: Message) -> None:
        sent.append(message)

    asyncio.run(BodySizeLimitMiddleware(app, max_body_bytes=limit)(_scope(), receive, send))
    return called, sent, bytes(received)


def test_body_limit_counts_chunked_requests_without_content_length() -> None:
    called, sent, _ = _run_body_limit(
        [
            {"type": "http.request", "body": b"abc", "more_body": True},
            {"type": "http.request", "body": b"def", "more_body": False},
        ],
        limit=5,
    )

    assert called is True
    assert sent[0]["status"] == 413


def test_body_limit_streams_allowed_chunked_request() -> None:
    called, sent, received = _run_body_limit(
        [
            {"type": "http.request", "body": b"ab", "more_body": True},
            {"type": "http.request", "body": b"cd", "more_body": False},
        ],
        limit=4,
    )

    assert called is True
    assert sent[0]["status"] == 204
    assert received == b"abcd"


def test_body_limit_does_not_prefetch_allowed_chunks() -> None:
    reads = 0

    async def receive() -> Message:
        nonlocal reads
        reads += 1
        return {
            "type": "http.request",
            "body": b"ab" if reads == 1 else b"cd",
            "more_body": reads == 1,
        }

    async def send(_message: Message) -> None:
        pass

    async def app(_scope: Scope, app_receive: Callable[[], Awaitable[Message]], _send: object) -> None:
        assert reads == 0
        assert (await app_receive())["body"] == b"ab"
        assert reads == 1
        assert (await app_receive())["body"] == b"cd"

    asyncio.run(BodySizeLimitMiddleware(app, max_body_bytes=4)(_scope(), receive, send))


def test_url_ingest_pins_the_validated_dns_address(monkeypatch: pytest.MonkeyPatch) -> None:
    async def resolve(_host: str, _port: int) -> list[str]:
        return ["93.184.216.34"]

    monkeypatch.setattr(url_ingest, "_resolve_host_ips", resolve)
    monkeypatch.setattr(url_ingest.settings, "URL_INGEST_ALLOW_PRIVATE_IPS", False)
    monkeypatch.setattr(url_ingest.settings, "URL_INGEST_ALLOWED_HOSTS", "")
    monkeypatch.setattr(url_ingest.settings, "URL_INGEST_ALLOWED_PORTS", "")

    target = asyncio.run(url_ingest._validated_fetch_target("https://example.com/path?q=1"))

    assert target.connect_url == "https://93.184.216.34:443/path?q=1"
    assert target.host == "example.com"
    assert target.host_header == "example.com:443"


def test_url_ingest_rejects_private_dns_answers(monkeypatch: pytest.MonkeyPatch) -> None:
    async def resolve(_host: str, _port: int) -> list[str]:
        return ["93.184.216.34", "127.0.0.1"]

    monkeypatch.setattr(url_ingest, "_resolve_host_ips", resolve)
    monkeypatch.setattr(url_ingest.settings, "URL_INGEST_ALLOW_PRIVATE_IPS", False)
    monkeypatch.setattr(url_ingest.settings, "URL_INGEST_ALLOWED_HOSTS", "")
    monkeypatch.setattr(url_ingest.settings, "URL_INGEST_ALLOWED_PORTS", "")

    with pytest.raises(HTTPException, match="url host is not allowed"):
        asyncio.run(url_ingest._validated_fetch_target("https://example.com/image.png"))


def test_url_download_connects_to_pinned_ip_with_original_sni(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    async def target(_url: str) -> object:
        return url_ingest._ValidatedFetchTarget(
            raw="https://example.com/image.png",
            connect_url="https://93.184.216.34:443/image.png",
            host="example.com",
            host_header="example.com:443",
        )

    class Response:
        status_code = 200
        headers = {"content-type": "image/png", "content-length": "2"}

        async def aiter_bytes(self):
            yield b"ok"

    class Stream:
        async def __aenter__(self):
            return Response()

        async def __aexit__(self, *_args: object) -> None:
            pass

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args: object) -> None:
            pass

        def stream(self, _method: str, request_url: str, **kwargs: object) -> Stream:
            captured.update(url=request_url, **kwargs)
            return Stream()

    def client_factory(**kwargs: object) -> Client:
        captured["client_kwargs"] = kwargs
        return Client()

    monkeypatch.setattr(url_ingest, "_validated_fetch_target", target)
    monkeypatch.setattr(url_ingest.httpx, "AsyncClient", client_factory)
    destination = tmp_path / "image.png"

    result = asyncio.run(url_ingest.download_url_to_path("https://example.com/image.png", destination))

    assert captured["url"] == "https://93.184.216.34:443/image.png"
    assert captured["client_kwargs"] == {
        "http2": False,
        "follow_redirects": False,
        "trust_env": False,
    }
    assert captured["extensions"] == {"sni_hostname": "example.com"}
    assert captured["headers"] == {"Accept": "*/*", "User-Agent": "MimirQ/1.0 (+url-ingest)", "Host": "example.com:443"}
    assert result.final_url == "https://example.com/image.png"
    assert destination.read_bytes() == b"ok"
