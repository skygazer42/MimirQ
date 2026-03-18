import pytest

from app.core.config import settings
from app.parsing.factory import ParserFactory


def test_factory_resolve_backend_marker_requires_enabled():
    factory = ParserFactory()
    with pytest.raises(ValueError):
        factory.resolve_backend(".pdf", "marker")


def test_factory_resolve_backend_marker_requires_api_url(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "MARKER_ENABLED", True)
    monkeypatch.setattr(settings, "MARKER_API_URL", "")
    factory = ParserFactory()
    with pytest.raises(ValueError):
        factory.resolve_backend(".pdf", "marker")


def test_factory_resolve_backend_marker_accepts_alias(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "MARKER_ENABLED", True)
    monkeypatch.setattr(settings, "MARKER_API_URL", "http://example/convert")
    factory = ParserFactory()
    assert factory.resolve_backend(".pdf", "marker-pdf") == "marker"


def test_factory_resolve_backend_paddlevl_requires_enabled():
    factory = ParserFactory()
    with pytest.raises(ValueError):
        factory.resolve_backend(".pdf", "paddle_vl")


def test_factory_resolve_backend_paddlevl_requires_api_url(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "PADDLE_VL_ENABLED", True)
    monkeypatch.setattr(settings, "PADDLE_VL_API_URL", "")
    factory = ParserFactory()
    with pytest.raises(ValueError):
        factory.resolve_backend(".pdf", "paddle_vl")


def test_factory_resolve_backend_paddlevl_accepts_alias(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "PADDLE_VL_ENABLED", True)
    monkeypatch.setattr(settings, "PADDLE_VL_API_URL", "http://example/convert")
    factory = ParserFactory()
    assert factory.resolve_backend(".pdf", "paddleocr-vl") == "paddle_vl"


def test_factory_resolve_backend_olmocr_requires_enabled():
    factory = ParserFactory()
    with pytest.raises(ValueError):
        factory.resolve_backend(".pdf", "olmocr")


def test_factory_resolve_backend_olmocr_requires_api_url(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "OLMOCR_ENABLED", True)
    monkeypatch.setattr(settings, "OLMOCR_API_URL", "")
    factory = ParserFactory()
    with pytest.raises(ValueError):
        factory.resolve_backend(".pdf", "olmocr")


def test_factory_resolve_backend_olmocr_accepts_alias(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "OLMOCR_ENABLED", True)
    monkeypatch.setattr(settings, "OLMOCR_API_URL", "http://example/convert")
    factory = ParserFactory()
    assert factory.resolve_backend(".pdf", "olm-ocr") == "olmocr"


def test_factory_resolve_backend_qianfan_ocr_requires_enabled():
    factory = ParserFactory()
    with pytest.raises(ValueError):
        factory.resolve_backend(".pdf", "qianfan_ocr")


def test_factory_resolve_backend_qianfan_ocr_requires_api_url(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "QIANFAN_OCR_ENABLED", True)
    monkeypatch.setattr(settings, "QIANFAN_OCR_API_URL", "")
    factory = ParserFactory()
    with pytest.raises(ValueError):
        factory.resolve_backend(".pdf", "qianfan_ocr")


def test_factory_resolve_backend_qianfan_ocr_accepts_alias(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "QIANFAN_OCR_ENABLED", True)
    monkeypatch.setattr(settings, "QIANFAN_OCR_API_URL", "http://example/convert")
    factory = ParserFactory()
    assert factory.resolve_backend(".pdf", "qianfan-ocr") == "qianfan_ocr"
