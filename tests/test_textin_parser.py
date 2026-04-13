from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import settings
from app.parsing.parsers.textin_parser import TextInParser


class _DummyResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self.status_code = status_code
        self.headers = {"content-type": "application/json"}
        self._payload = payload
        self.text = __import__("json").dumps(payload, ensure_ascii=False)
        self.content = self.text.encode("utf-8")

    def json(self):  # noqa: ANN001
        return self._payload


class _DummySession:
    def __init__(self, response: _DummyResponse) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def post(self, url: str, *, params: dict[str, str], data: bytes, headers: dict[str, str], timeout: float):
        self.calls.append(
            {
                "url": url,
                "params": params,
                "data_len": len(data),
                "headers": headers,
                "timeout": timeout,
            }
        )
        return self.response


def _enable_textin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "TEXTIN_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "TEXTIN_API_URL", "https://api.textin.com/ai/service/v1/pdf_to_markdown", raising=False)
    monkeypatch.setattr(settings, "TEXTIN_APP_ID", "demo-app-id", raising=False)
    monkeypatch.setattr(settings, "TEXTIN_SECRET_CODE", "demo-secret", raising=False)
    monkeypatch.setattr(settings, "TEXTIN_TIMEOUT_SEC", 45, raising=False)
    monkeypatch.setattr(settings, "TEXTIN_PARSE_MODE", "auto", raising=False)
    monkeypatch.setattr(settings, "TEXTIN_TABLE_FLAVOR", "html", raising=False)
    monkeypatch.setattr(settings, "TEXTIN_APPLY_DOCUMENT_TREE", True, raising=False)
    monkeypatch.setattr(settings, "TEXTIN_MARKDOWN_DETAILS", True, raising=False)
    monkeypatch.setattr(settings, "TEXTIN_GET_IMAGE", "none", raising=False)
    monkeypatch.setattr(settings, "TEXTIN_DPI", 144, raising=False)
    monkeypatch.setattr(settings, "TEXTIN_PAGE_COUNT", 0, raising=False)


def test_textin_parser_posts_binary_with_expected_headers_and_params(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _enable_textin(monkeypatch)

    parser = TextInParser()
    parser._session = _DummySession(_DummyResponse({"code": 200, "result": {"markdown": "# textin ok"}}))  # type: ignore[assignment]

    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%textin-test\n")

    docs = parser.parse(pdf_path)

    assert docs[0].page_content == "# textin ok"
    call = parser._session.calls[0]  # type: ignore[attr-defined]
    assert call["url"] == "https://api.textin.com/ai/service/v1/pdf_to_markdown"
    assert call["params"] == {
        "parse_mode": "auto",
        "table_flavor": "html",
        "apply_document_tree": "true",
        "markdown_details": "true",
        "get_image": "none",
        "dpi": "144",
    }
    assert call["headers"]["x-ti-app-id"] == "demo-app-id"  # type: ignore[index]
    assert call["headers"]["x-ti-secret-code"] == "demo-secret"  # type: ignore[index]


def test_textin_parser_falls_back_to_joined_result_text(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _enable_textin(monkeypatch)

    payload = {
        "code": 200,
        "result": {
            "elements": [
                {"text": "Title"},
                {"content": "Body"},
            ]
        },
    }
    parser = TextInParser()
    parser._session = _DummySession(_DummyResponse(payload))  # type: ignore[assignment]

    pdf_path = tmp_path / "sample.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%textin-test\n")

    docs = parser.parse(pdf_path)

    assert "Title" in docs[0].page_content
    assert "Body" in docs[0].page_content
