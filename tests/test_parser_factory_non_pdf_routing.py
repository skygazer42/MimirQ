from app.core.config import settings
from app.parsing.factory import ParserFactory


def test_non_pdf_auto_routes_xlsx_to_excel(monkeypatch):
    monkeypatch.setattr(settings, "PANDOC_ENABLED", False, raising=False)
    factory = ParserFactory()
    assert factory.resolve_backend(".xlsx", None) == "excel"


def test_non_pdf_auto_routes_docx_to_markitdown_when_pandoc_disabled(monkeypatch):
    monkeypatch.setattr(settings, "PANDOC_ENABLED", False, raising=False)
    factory = ParserFactory()
    assert factory.resolve_backend(".docx", None) == "markitdown"


def test_non_pdf_auto_routes_docx_to_pandoc_when_enabled(monkeypatch):
    monkeypatch.setattr(settings, "PANDOC_ENABLED", True, raising=False)
    factory = ParserFactory()
    assert factory.resolve_backend(".docx", None) == "pandoc"


def test_non_pdf_auto_routes_doc_to_markitdown_without_libreoffice(monkeypatch):
    monkeypatch.setattr(settings, "PANDOC_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "LIBREOFFICE_ENABLED", False, raising=False)
    factory = ParserFactory()
    assert factory.resolve_backend(".doc", None) == "markitdown"


def test_non_pdf_auto_routes_doc_to_pandoc_with_libreoffice(monkeypatch):
    monkeypatch.setattr(settings, "PANDOC_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "LIBREOFFICE_ENABLED", True, raising=False)
    factory = ParserFactory()
    assert factory.resolve_backend(".doc", None) == "pandoc"

