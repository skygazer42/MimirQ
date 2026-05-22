import pytest

from app.core.config import settings
from app.parsing.factory import ParserFactory


def test_factory_resolve_backend_magicpdf_requires_enabled(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "MAGIC_PDF_ENABLED", False, raising=False)
    factory = ParserFactory()
    with pytest.raises(ValueError):
        factory.resolve_backend(".pdf", "magicpdf")


def test_factory_resolve_backend_magicpdf_accepts_alias(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "MAGIC_PDF_ENABLED", True)
    monkeypatch.setattr(ParserFactory, "_magicpdf_runtime_ready", staticmethod(lambda: True))
    factory = ParserFactory()
    assert factory.resolve_backend(".pdf", "magic-pdf") == "magicpdf"


def test_factory_resolve_backend_magicpdf_accepts_service_url_without_cli_models(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "MAGIC_PDF_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "MAGIC_PDF_API_URL", "http://mimirq-magicpdf:2095/convert", raising=False)
    monkeypatch.setattr(settings, "MAGIC_PDF_CLI", "missing-magic-pdf", raising=False)
    monkeypatch.setattr(settings, "MAGIC_PDF_MODELS_DIR", "", raising=False)

    factory = ParserFactory()

    assert factory.resolve_backend(".pdf", "magicpdf") == "magicpdf"


def test_factory_resolve_backend_magicpdf_requires_models(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "MAGIC_PDF_ENABLED", True)
    monkeypatch.setattr(settings, "MAGIC_PDF_API_URL", "", raising=False)
    monkeypatch.setattr(ParserFactory, "_magicpdf_runtime_ready", staticmethod(lambda: False))
    factory = ParserFactory()
    with pytest.raises(ValueError, match="PDF-Extract-Kit models"):
        factory.resolve_backend(".pdf", "magicpdf")
