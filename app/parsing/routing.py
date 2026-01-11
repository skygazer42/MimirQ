"""
PDF parsing router (auto-selection) utility.

Unified usage in:
- Preview parsing (parse-preview)
- Database parsing (documents/upload background processing)
"""

from pathlib import Path
from typing import Dict, Optional, Tuple

from app.core.config import settings
from app.parsing.backends import normalize_parser_backend
from app.parsing.utils.cli import resolve_cli_command


def choose_pdf_backend(quality: Optional[Dict], requested: Optional[str]) -> str:
    """
    Choose a PDF parser backend based on quality scoring and user request.

    Rules:
    - requested is set and not "auto" -> honor requested (even if not configured; validation happens later).
    - score >= 0.8 and not scanned -> prefer Docling (structure) then MarkItDown/basic.
    - scanned or score <= 0.5 -> prefer MinerU (if configured) / DeepSeek OCR / Bisheng-Unstructured / DeepDoc,
      fallback Docling/MagicPDF/MarkItDown/basic.
    - mid range -> prefer Docling/DeepDoc/MinerU/Bisheng-Unstructured, fallback MagicPDF/MarkItDown/basic.
    """
    quality = quality or {}
    score = float(quality.get("score", 0.0) or 0.0)
    is_scanned = bool(quality.get("is_scanned", False))

    def _magicpdf_available() -> bool:
        if not bool(getattr(settings, "MAGIC_PDF_ENABLED", False)):
            return False
        cli = (getattr(settings, "MAGIC_PDF_CLI", "") or "magic-pdf").strip() or "magic-pdf"
        return bool(resolve_cli_command(cli))

    requested_norm = normalize_parser_backend(requested)
    if requested_norm and requested_norm != "auto":
        return requested_norm

    bisheng_ok = bool(getattr(settings, "BISHENG_UNSTRUCTURED_ENABLED", False)) and bool(
        (getattr(settings, "BISHENG_UNSTRUCTURED_API_URL", "") or "").strip()
    )
    deepseek_ocr_ok = bool(getattr(settings, "DEEPSEEK_OCR_ENABLED", False)) and bool(
        (getattr(settings, "SILICONFLOW_API_KEY", "") or "").strip()
    )

    if score >= 0.8 and not is_scanned:
        if getattr(settings, "DOCLING_ENABLED", False):
            return "docling"
        if bisheng_ok:
            return "bisheng_unstructured"
        if settings.MARKITDOWN_ENABLED:
            return "markitdown"
        if settings.DEEPDOC_ENABLED:
            return "deepdoc"
        return "basic"

    if is_scanned or score <= 0.5:
        if settings.MINERU_ENABLED and (settings.MINERU_API_TOKEN or settings.MINERU_LOCAL_SERVER_URL):
            return "mineru"
        if deepseek_ocr_ok:
            return "deepseek_ocr"
        if bisheng_ok:
            return "bisheng_unstructured"
        if settings.DEEPDOC_ENABLED:
            return "deepdoc"
        if getattr(settings, "DOCLING_ENABLED", False):
            return "docling"
        if _magicpdf_available():
            return "magicpdf"
        if settings.MARKITDOWN_ENABLED:
            return "markitdown"
        return "basic"

    if getattr(settings, "DOCLING_ENABLED", False):
        return "docling"
    if bisheng_ok:
        return "bisheng_unstructured"
    if settings.DEEPDOC_ENABLED:
        return "deepdoc"
    if settings.MINERU_ENABLED and (settings.MINERU_API_TOKEN or settings.MINERU_LOCAL_SERVER_URL):
        return "mineru"
    if _magicpdf_available():
        return "magicpdf"
    if settings.MARKITDOWN_ENABLED:
        return "markitdown"
    return "basic"


def route_pdf_backend(
    file_path: Path,
    requested: Optional[str],
    *,
    sample_pages: int = 3,
    use_ocr_validation: Optional[bool] = None,
) -> Tuple[str, Dict]:
    """
    Score a PDF and return (chosen_backend, quality).
    """
    from app.parsing.quality.scorer import score_pdf_quality

    use_ocr = settings.RAPIDOCR_ENABLED if use_ocr_validation is None else bool(use_ocr_validation)
    quality = score_pdf_quality(file_path, sample_pages=sample_pages, use_ocr_validation=use_ocr)
    return choose_pdf_backend(quality, requested), quality
