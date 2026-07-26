import json
from http.client import RemoteDisconnected

from scripts import api_ping, compose_diagnostics


class _Response:
    status = 200
    headers = {"Content-Type": "application/json"}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self) -> bytes:
        return json.dumps({"ok": True}).encode()


def test_read_json_bypasses_proxy_for_loopback(monkeypatch) -> None:
    class _Opener:
        def open(self, request, *, timeout):
            assert request.full_url == "http://127.0.0.1:8000/api/v1/health"
            assert timeout == 1.0
            return _Response()

    def build_no_proxy_opener(handler):
        assert handler.proxies == {}
        return _Opener()

    monkeypatch.setattr(api_ping, "build_opener", build_no_proxy_opener)
    monkeypatch.setattr(api_ping, "urlopen", lambda *_args, **_kwargs: AssertionError("proxy-aware urlopen used"))

    result = api_ping._read_json("http://127.0.0.1:8000/api/v1/health", timeout_sec=1.0)

    assert result.status_code == 200
    assert result.data == {"ok": True}


def test_read_json_returns_structured_error_for_connection_reset(monkeypatch) -> None:
    def raise_connection_reset(*_args, **_kwargs):
        raise ConnectionResetError("peer reset")

    monkeypatch.setattr(api_ping, "urlopen", raise_connection_reset)

    result = api_ping._read_json("http://example.com/api/v1/health", timeout_sec=1.0)

    assert result.status_code is None
    assert result.data is None
    assert result.error == "ConnectionResetError: peer reset"


def test_read_json_returns_structured_error_for_remote_disconnect(monkeypatch) -> None:
    def raise_remote_disconnect(*_args, **_kwargs):
        raise RemoteDisconnected("remote closed connection without response")

    monkeypatch.setattr(api_ping, "urlopen", raise_remote_disconnect)

    result = api_ping._read_json("http://example.com/api/v1/health", timeout_sec=1.0)

    assert result.status_code is None
    assert result.data is None
    assert result.error == "RemoteDisconnected: remote closed connection without response"


def test_compose_diagnostics_bypasses_proxy_for_loopback(monkeypatch) -> None:
    class _Opener:
        def open(self, request, *, timeout):
            assert request.full_url == "http://localhost:8000/api/v1/health/ready"
            assert timeout == 1.0
            return _Response()

    def build_no_proxy_opener(handler):
        assert handler.proxies == {}
        return _Opener()

    monkeypatch.setattr(compose_diagnostics.urllib.request, "build_opener", build_no_proxy_opener)
    monkeypatch.setattr(
        compose_diagnostics.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: AssertionError("proxy-aware urlopen used"),
    )

    result = compose_diagnostics._check_backend_ready(
        url="http://localhost:8000/api/v1/health/ready",
        timeout_sec=1.0,
    )

    assert result["ok"] is True
    assert result["status_code"] == 200
