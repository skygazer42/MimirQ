from __future__ import annotations

from pathlib import Path

from app.core.config import settings
from app.parsing.parsers.marker_parser import MarkerParser


class _DummyResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class _DummySession:
    def __init__(self, responses: list[_DummyResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def post(self, url: str, *, files: dict[str, object], data: dict[str, object], timeout: float):
        self.calls.append({"url": url, "files": files, "data": data, "timeout": timeout})
        return self._responses.pop(0)


def test_marker_parser_retries_marker_upload_fallback_for_legacy_convert_url(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "MARKER_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "MARKER_API_URL", "http://marker.local:2080/convert", raising=False)
    monkeypatch.setattr(settings, "MARKER_TIMEOUT_SEC", 123, raising=False)

    parser = MarkerParser()
    parser._session = _DummySession([_DummyResponse(404), _DummyResponse(200)])

    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%marker-test\n")

    resp = parser._post_multipart(file_path=pdf_path)

    assert resp.status_code == 200
    assert [call["url"] for call in parser._session.calls] == [
        "http://marker.local:2080/convert",
        "http://marker.local:2080/marker/upload",
    ]
    assert parser._session.calls[0]["data"] == {"output_format": "markdown"}
    assert parser._session.calls[0]["timeout"] == 123


def test_marker_parser_uses_marker_upload_without_retry_when_already_configured(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "MARKER_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "MARKER_API_URL", "http://marker.local:2080/marker/upload", raising=False)
    monkeypatch.setattr(settings, "MARKER_TIMEOUT_SEC", 45, raising=False)

    parser = MarkerParser()
    parser._session = _DummySession([_DummyResponse(200)])

    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%marker-test\n")

    resp = parser._post_multipart(file_path=pdf_path)

    assert resp.status_code == 200
    assert [call["url"] for call in parser._session.calls] == [
        "http://marker.local:2080/marker/upload",
    ]


def test_marker_parser_extracts_output_field_from_json_payload() -> None:
    assert MarkerParser._extract_markdown_from_json(
        {"format": "markdown", "output": "## marker markdown"}
    ) == "## marker markdown"
