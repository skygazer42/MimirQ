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
    factory = ParserFactory()
    assert factory.resolve_backend(".pdf", "magic-pdf") == "magicpdf"

