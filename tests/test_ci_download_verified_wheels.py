import hashlib
import io
import urllib.request

from ci import download_verified_wheels


def test_download_uses_an_explicit_service_user_agent(monkeypatch, tmp_path) -> None:
    payload = b"verified wheel payload"
    spec = download_verified_wheels.WheelSpec(
        filename="fixture.whl",
        url="https://download.example.invalid/fixture.whl",
        sha256=hashlib.sha256(payload).hexdigest(),
    )
    observed: dict[str, object] = {}

    def fake_urlopen(request: urllib.request.Request, timeout: int):
        observed["request"] = request
        observed["timeout"] = timeout
        return io.BytesIO(payload)

    monkeypatch.setattr(download_verified_wheels.urllib.request, "urlopen", fake_urlopen)

    target = tmp_path / spec.filename
    download_verified_wheels._download(spec, target, retries=1, timeout_sec=17)

    request = observed["request"]
    assert isinstance(request, urllib.request.Request)
    assert request.full_url == spec.url
    assert request.get_header("User-agent") == download_verified_wheels.WHEEL_DOWNLOAD_USER_AGENT
    assert observed["timeout"] == 17
    assert target.read_bytes() == payload
