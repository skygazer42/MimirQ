import asyncio
from collections.abc import Awaitable, Callable
from ipaddress import IPv4Address, IPv6Address, ip_address
from pathlib import Path

import pytest
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.testclient import TestClient
from starlette.middleware.exceptions import ExceptionMiddleware
from starlette.types import Message, Receive, Scope, Send

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


def _run_body_limit(
    messages: list[Message],
    *,
    limit: int,
    headers: list[tuple[bytes, bytes]] | None = None,
) -> tuple[bool, list[Message], bytes]:
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

    application = BodySizeLimitMiddleware(ExceptionMiddleware(app), max_body_bytes=limit)
    asyncio.run(application(_scope(headers), receive, send))
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


@pytest.mark.parametrize("length", [b"", b"invalid", b"-1", b"1, 2"])
def test_body_limit_rejects_invalid_content_length(length: bytes) -> None:
    called, sent, _ = _run_body_limit([], limit=4, headers=[(b"content-length", length)])
    assert called is False
    assert sent[0]["status"] == 400


def test_body_limit_rejects_large_content_length_before_reading() -> None:
    called, sent, _ = _run_body_limit([], limit=4, headers=[(b"content-length", b"5")])
    assert called is False
    assert sent[0]["status"] == 413


def test_body_limit_still_counts_bytes_when_content_length_understates_size() -> None:
    called, sent, _ = _run_body_limit(
        [{"type": "http.request", "body": b"abcde", "more_body": False}],
        limit=4,
        headers=[(b"content-length", b"1")],
    )
    assert called is True
    assert sent[0]["status"] == 413


def test_body_limit_returns_413_when_fastapi_parses_chunked_json() -> None:
    app = FastAPI()
    app.add_middleware(BodySizeLimitMiddleware, max_body_bytes=10)

    @app.post("/upload")
    async def upload(payload: dict) -> dict:
        return payload

    with TestClient(app) as client:
        response = client.post(
            "/upload",
            content=iter([b'{"message":', b'"too large"}']),
            headers={"Content-Type": "application/json"},
        )

    assert response.status_code == 413
    assert response.json() == {"detail": "Request body too large"}


def test_body_limit_returns_413_when_fastapi_parses_chunked_multipart() -> None:
    app = FastAPI()
    app.add_middleware(BodySizeLimitMiddleware, max_body_bytes=100)

    @app.post("/upload")
    async def upload(file: UploadFile = File(...)) -> dict:
        return {"size": len(await file.read())}

    chunks = [
        b'--boundary\r\nContent-Disposition: form-data; name="file"; filename="notes.txt"\r\n\r\n',
        b"x" * 100,
        b"\r\n--boundary--\r\n",
    ]
    with TestClient(app) as client:
        response = client.post(
            "/upload",
            content=iter(chunks),
            headers={"Content-Type": "multipart/form-data; boundary=boundary"},
        )

    assert response.status_code == 413
    assert response.json() == {"detail": "Request body too large"}


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


@pytest.mark.parametrize("limit", [0, -1])
def test_disabled_body_limit_passes_the_request_through(limit: int) -> None:
    called, sent, received = _run_body_limit(
        [{"type": "http.request", "body": b"abcde", "more_body": False}],
        limit=limit,
    )
    assert called is True
    assert sent[0]["status"] == 204
    assert received == b"abcde"


def test_body_limit_does_not_send_a_second_response_after_headers_started() -> None:
    sent: list[Message] = []

    async def app(_request_scope: Scope, receive: Receive, send: Send) -> None:
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await receive()

    async def receive() -> Message:
        return {"type": "http.request", "body": b"abcde", "more_body": False}

    async def send(message: Message) -> None:
        sent.append(message)

    application = BodySizeLimitMiddleware(ExceptionMiddleware(app), max_body_bytes=4)
    with pytest.raises(RuntimeError, match="response already started"):
        asyncio.run(application(_scope(), receive, send))

    assert [message["status"] for message in sent if message["type"] == "http.response.start"] == [200]


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
    async def resolve(_host: str, _port: int) -> list[IPv4Address | IPv6Address]:
        return [ip_address("93.184.216.34")]

    monkeypatch.setattr(url_ingest, "_resolve_host_addresses", resolve)
    monkeypatch.setattr(url_ingest.settings, "URL_INGEST_ALLOW_PRIVATE_IPS", False)
    monkeypatch.setattr(url_ingest.settings, "URL_INGEST_ALLOWED_HOSTS", "")
    monkeypatch.setattr(url_ingest.settings, "URL_INGEST_ALLOWED_PORTS", "")

    target = asyncio.run(url_ingest.validate_fetch_target("https://example.com/path?q=1"))

    assert target.connect_url == "https://93.184.216.34:443/path?q=1"
    assert target.host == "example.com"
    assert target.host_header == "example.com:443"


def test_url_ingest_rejects_private_dns_answers(monkeypatch: pytest.MonkeyPatch) -> None:
    async def resolve(_host: str, _port: int) -> list[IPv4Address | IPv6Address]:
        return [ip_address("93.184.216.34"), ip_address("127.0.0.1")]

    monkeypatch.setattr(url_ingest, "_resolve_host_addresses", resolve)
    monkeypatch.setattr(url_ingest.settings, "URL_INGEST_ALLOW_PRIVATE_IPS", False)
    monkeypatch.setattr(url_ingest.settings, "URL_INGEST_ALLOWED_HOSTS", "")
    monkeypatch.setattr(url_ingest.settings, "URL_INGEST_ALLOWED_PORTS", "")

    with pytest.raises(HTTPException, match="url host is not allowed"):
        asyncio.run(url_ingest.validate_fetch_target("https://example.com/image.png"))


def test_url_ingest_can_skip_allowlists_without_skipping_dns_ssrf_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    async def resolve(_host: str, _port: int) -> list[IPv4Address | IPv6Address]:
        return [ip_address("93.184.216.34")]

    monkeypatch.setattr(url_ingest, "_resolve_host_addresses", resolve)
    monkeypatch.setattr(url_ingest.settings, "URL_INGEST_ALLOW_PRIVATE_IPS", False)
    monkeypatch.setattr(url_ingest.settings, "URL_INGEST_ALLOWED_HOSTS", "allowed.example.com")
    monkeypatch.setattr(url_ingest.settings, "URL_INGEST_ALLOWED_PORTS", "443")

    target = asyncio.run(url_ingest.validate_fetch_target("https://api.example.com/v1", enforce_allowlists=False))

    assert target.connect_url == "https://93.184.216.34:443/v1"
    assert target.host_header == "api.example.com:443"


def test_url_download_connects_to_pinned_ip_with_original_sni(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    target = url_ingest.ValidatedFetchTarget(
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

    monkeypatch.setattr(url_ingest.httpx, "AsyncClient", client_factory)
    destination = tmp_path / "image.png"

    result = asyncio.run(
        url_ingest.download_url_to_path(target, destination, max_bytes=100, timeout_sec=1.0, follow_redirects=False)
    )

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
