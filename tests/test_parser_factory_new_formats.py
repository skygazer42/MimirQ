from __future__ import annotations

import pytest

from app.core.config import settings
from app.parsing.factory import ParserFactory


def test_parser_factory_resolves_eml_and_image(monkeypatch) -> None:
    factory = ParserFactory()
    assert factory.resolve_backend(".eml", None) == "email"
    assert factory.resolve_backend(".msg", None) == "email"
    assert factory.resolve_backend(".png", None) == "image"

    monkeypatch.setattr(settings, "PANDOC_ENABLED", False, raising=False)
    assert factory.resolve_backend(".rtf", None) == "markitdown"

    monkeypatch.setattr(settings, "PANDOC_ENABLED", True, raising=False)
    assert factory.resolve_backend(".rtf", None) == "pandoc"


def test_parser_factory_glm_ocr_requires_enable(monkeypatch) -> None:
    factory = ParserFactory()
    monkeypatch.setattr(settings, "GLM_OCR_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "GLM_OCR_API_URL", "", raising=False)
    with pytest.raises(ValueError):
        factory.resolve_backend(".pdf", "glm_ocr")

    monkeypatch.setattr(settings, "GLM_OCR_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "GLM_OCR_API_URL", "", raising=False)
    with pytest.raises(ValueError):
        factory.resolve_backend(".pdf", "glm_ocr")
