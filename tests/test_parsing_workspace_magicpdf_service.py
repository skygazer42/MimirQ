from __future__ import annotations

from app.core.config import settings


def test_parsing_workspace_fallback_candidates_include_magicpdf_service(monkeypatch) -> None:  # noqa: ANN001
    import app.api.v1.parsing as parsing_module

    monkeypatch.setattr(settings, "MINERU_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "DEEPSEEK_OCR_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "QIANFAN_OCR_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "ETL4LLM_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "DEEPDOC_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "DOCLING_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "MARKITDOWN_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "MAGIC_PDF_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "MAGIC_PDF_API_URL", "http://mimirq-magicpdf:2095/convert", raising=False)
    monkeypatch.setattr(settings, "MAGIC_PDF_CLI", "missing-magic-pdf", raising=False)
    monkeypatch.setattr(settings, "MAGIC_PDF_MODELS_DIR", "", raising=False)

    assert parsing_module._build_pdf_fallback_candidates() == ["magicpdf", "basic"]
