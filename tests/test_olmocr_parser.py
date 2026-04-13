from __future__ import annotations

from pathlib import Path

import requests

from app.core.config import settings
from app.parsing.parsers.olmocr_parser import OlmocrParser


class _DummyJsonResponse:
    def __init__(self, payload: dict) -> None:
        self.status_code = 200
        self.headers = {"content-type": "application/json"}
        self._payload = payload
        self.text = ""
        self.content = b"{}"

    def json(self):  # noqa: ANN001
        return self._payload


class _TimeoutThenJsonSession:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def post(self, url: str, *, files: dict[str, object], data: dict[str, object], timeout: float):
        self.calls.append(url)
        if len(self.calls) == 1:
            raise requests.exceptions.ReadTimeout(f"timeout for {url}")
        return _DummyJsonResponse({"markdown": "# olmocr ok"})


def test_olmocr_parser_retries_localhost_when_service_alias_times_out(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(settings, "OLMOCR_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "OLMOCR_API_URL", "http://mimirq-olmocr:2085/convert", raising=False)
    monkeypatch.setattr(settings, "OLMOCR_TIMEOUT_SEC", 3, raising=False)

    parser = OlmocrParser()
    parser._session = _TimeoutThenJsonSession()

    pdf_path = tmp_path / "input.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake\n")

    docs = parser.parse(pdf_path)

    assert docs and docs[0].page_content == "# olmocr ok"
    assert parser._session.calls == [
        "http://mimirq-olmocr:2085/convert",
        "http://127.0.0.1:2085/convert",
    ]
