from pathlib import Path
from typing import Any

import pytest
import requests

from app.core.config import settings
from app.services.docling_service import (
    DoclingServiceParser,
    docling_convert_url,
    docling_health_url,
    normalize_docling_base_url,
)


class _FakeResponse:
    def __init__(self, payload: Any, *, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"status={self.status_code}")

    def json(self) -> Any:
        return self._payload


class _FakeSession:
    def __init__(self, *, health: _FakeResponse, conversion: _FakeResponse) -> None:
        self.health = health
        self.conversion = conversion
        self.get_calls: list[tuple[str, dict[str, Any]]] = []
        self.post_calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.get_calls.append((url, kwargs))
        return self.health

    def post(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.post_calls.append((url, kwargs))
        return self.conversion


@pytest.mark.parametrize(
    "configured",
    [
        "http://docling:5001",
        "http://docling:5001/",
        "http://docling:5001/v1",
        "http://docling:5001/v1/convert/file",
    ],
)
def test_docling_service_url_normalization_accepts_base_and_endpoint(configured: str) -> None:
    assert normalize_docling_base_url(configured) == "http://docling:5001"
    assert docling_convert_url(configured) == "http://docling:5001/v1/convert/file"
    assert docling_health_url(configured) == "http://docling:5001/health"


def test_docling_service_health_and_conversion_use_stable_v1_contract(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(settings, "DOCLING_ENABLED", True, raising=False)
    session = _FakeSession(
        health=_FakeResponse({"status": "ok"}),
        conversion=_FakeResponse(
            {
                "status": "success",
                "document": {"md_content": "# Parsed\n\n| A | B |"},
                "errors": [],
            }
        ),
    )
    parser = DoclingServiceParser(
        api_url="http://docling:5001/v1/convert/file",
        api_key="secret",
        request_timeout_sec=45,
        health_timeout_sec=2,
        ocr_enabled=True,
        session=session,  # type: ignore[arg-type]
    )
    source = tmp_path / "sample.pdf"
    source.write_bytes(b"%PDF-1.4\n")
    progress: list[tuple[float, str]] = []

    assert parser.check_installation() is True
    sections, tables = parser.parse_pdf(source, callback=lambda value, message: progress.append((value, message)))

    assert sections == [("# Parsed\n\n| A | B |", "")]
    assert tables == []
    assert session.get_calls == [
        (
            "http://docling:5001/health",
            {"headers": {"X-Api-Key": "secret"}, "timeout": 2.0},
        )
    ]
    post_url, post_kwargs = session.post_calls[0]
    assert post_url == "http://docling:5001/v1/convert/file"
    assert post_kwargs["headers"] == {"X-Api-Key": "secret"}
    assert post_kwargs["files"]["files"] == ("sample.pdf", b"%PDF-1.4\n", "application/pdf")
    assert dict(post_kwargs["data"])["from_formats"] == "pdf"
    assert dict(post_kwargs["data"])["to_formats"] == "md"
    assert dict(post_kwargs["data"])["do_ocr"] == "true"
    assert post_kwargs["timeout"] == 45.0
    assert progress[0][0] == 0.1
    assert progress[-1][0] == 1.0


def test_docling_service_requires_external_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "DOCLING_ENABLED", True, raising=False)
    parser = DoclingServiceParser(api_url="")

    assert parser.check_installation() is False
    assert parser.trust_env is False
    assert parser._session.trust_env is False
    assert parser.unavailable_reason == "DOCLING_API_URL is not configured"
    with pytest.raises(RuntimeError, match="requires DOCLING_API_URL"):
        parser.parse_pdf("missing.pdf")


def test_docling_service_rejects_failed_or_empty_conversion(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(settings, "DOCLING_ENABLED", True, raising=False)
    source = tmp_path / "sample.docx"
    source.write_bytes(b"docx")
    session = _FakeSession(
        health=_FakeResponse({"status": "ok"}),
        conversion=_FakeResponse({"status": "failure", "errors": [{"message": "bad input"}]}),
    )
    parser = DoclingServiceParser(api_url="http://docling:5001", session=session)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="Docling conversion failed"):
        parser.parse_pdf(source)
