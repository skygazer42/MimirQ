from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest
from langchain_core.documents import Document

from app.core.config import settings
from app.parsing.factory import ParserFactory
from app.parsing.processors import parser_service


class _FailingParser:
    def parse(self, *_args, **_kwargs):  # noqa: ANN001, ANN202
        raise RuntimeError("primary parser unavailable")


class _BasicParser:
    def parse(self, *_args, **_kwargs):  # noqa: ANN001, ANN202
        return [Document(page_content="basic fallback", metadata={})]


def test_parser_factory_can_disable_pdf_backend_fallback(monkeypatch, tmp_path: Path) -> None:  # noqa: ANN001
    monkeypatch.setattr(settings, "OLMOCR_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "OLMOCR_API_URL", "http://mimirq-olmocr:2085/convert", raising=False)
    factory = ParserFactory()

    def get_parser(backend: str):  # noqa: ANN202
        return _FailingParser() if backend == "olmocr" else _BasicParser()

    monkeypatch.setattr(factory, "_get_pdf_parser", get_parser)
    pdf_path = tmp_path / "input.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake\n")

    docs, resolved = factory.parse(pdf_path, parser_backend="olmocr")
    assert resolved == "basic"
    assert docs[0].page_content == "basic fallback"

    with pytest.raises(RuntimeError, match="primary parser unavailable"):
        factory.parse(pdf_path, parser_backend="olmocr", allow_fallback=False)


def test_parse_preview_disables_fallback_for_explicit_pdf_backend(monkeypatch, tmp_path: Path) -> None:  # noqa: ANN001
    captured: dict[str, object] = {}

    def fake_route(_file_path, requested, **_kwargs):  # noqa: ANN001, ANN202
        return requested, {"score": 0.7}

    def fake_parse(_file_path, **kwargs):  # noqa: ANN001, ANN202
        captured.update(kwargs)
        return [Document(page_content="olmocr markdown", metadata={})], "olmocr"

    monkeypatch.setattr(parser_service, "route_pdf_backend", fake_route)
    monkeypatch.setattr(parser_service.parser_factory, "parse", fake_parse)

    pdf_path = tmp_path / "input.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake\n")

    service = parser_service.DocumentParserService()
    result = service.parse_for_preview(
        pdf_path,
        tenant_id=UUID("00000000-0000-0000-0000-000000000000"),
        parser_backend="olmocr",
    )

    assert result["backend"] == "olmocr"
    assert captured["allow_fallback"] is False


def test_parse_preview_allows_fallback_for_auto_pdf_backend(monkeypatch, tmp_path: Path) -> None:  # noqa: ANN001
    captured: dict[str, object] = {}

    def fake_route(_file_path, _requested, **_kwargs):  # noqa: ANN001, ANN202
        return "docling", {"score": 0.7}

    def fake_parse(_file_path, **kwargs):  # noqa: ANN001, ANN202
        captured.update(kwargs)
        return [Document(page_content="auto markdown", metadata={})], "docling"

    monkeypatch.setattr(parser_service, "route_pdf_backend", fake_route)
    monkeypatch.setattr(parser_service.parser_factory, "parse", fake_parse)

    pdf_path = tmp_path / "input.pdf"
    pdf_path.write_bytes(b"%PDF-1.4 fake\n")

    service = parser_service.DocumentParserService()
    result = service.parse_for_preview(
        pdf_path,
        tenant_id=UUID("00000000-0000-0000-0000-000000000000"),
        parser_backend="auto",
    )

    assert result["backend"] == "docling"
    assert captured["allow_fallback"] is True
