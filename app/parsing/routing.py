"""
PDF parsing router (auto-selection) utility.

Unified usage in:
- Preview parsing (parse-preview)
- Database parsing (documents/upload background processing)
"""

from pathlib import Path

from app.core.config import settings
from app.parsing.backends import normalize_parser_backend
from app.parsing.parsers.magic_pdf_parser import resolve_magicpdf_models_dir
from app.parsing.utils.cli import resolve_cli_command


def should_attempt_pdf_fallback(
    *,
    grade: str | None,
    parse_score: float | None,
    content_chars: int | None,
    min_content_chars: int,
    min_parse_score: float,
) -> bool:
    """
    Decide whether a low-quality parse should trigger an alternative backend retry.

    Conditions:
    - hard fail always retries
    - too-short content retries
    - low parse quality score retries when threshold > 0
    """
    grade_norm = str(grade or "").strip().lower()
    if grade_norm == "fail":
        return True

    chars = max(0, int(content_chars or 0))
    if int(min_content_chars or 0) > 0 and chars < int(min_content_chars or 0):
        return True

    if float(min_parse_score or 0.0) > 0.0 and parse_score is not None:
        try:
            score = float(parse_score)
        except (TypeError, ValueError):
            score = None
        if score is not None and score < float(min_parse_score):
            return True

    return False


def choose_pdf_backend(quality: dict | None, requested: str | None) -> str:
    """
    Choose a PDF parser backend based on quality scoring and user request.

    Rules:
    - requested is set and not "auto" -> honor requested (even if not configured; validation happens later).
    - score >= 0.8 and not scanned -> prefer Docling (structure) then MarkItDown/basic.
    - scanned or score <= 0.5 -> prefer MinerU (if configured) / DeepSeek OCR / ETL4LLM / DeepDoc,
      fallback Docling/MagicPDF/MarkItDown/basic.
    - mid range -> prefer Docling/DeepDoc/MinerU/ETL4LLM, fallback MagicPDF/MarkItDown/basic.
    """
    quality = quality or {}
    score = float(quality.get("score", 0.0) or 0.0)
    is_scanned = bool(quality.get("is_scanned", False))

    def _magicpdf_available() -> bool:
        if not bool(getattr(settings, "MAGIC_PDF_ENABLED", False)):
            return False
        cli = (getattr(settings, "MAGIC_PDF_CLI", "") or "magic-pdf").strip() or "magic-pdf"
        return bool(
            resolve_cli_command(cli)
            and resolve_magicpdf_models_dir(getattr(settings, "MAGIC_PDF_MODELS_DIR", ""))
        )

    requested_norm = normalize_parser_backend(requested)
    if requested_norm and requested_norm != "auto":
        return requested_norm

    etl4llm_ok = bool(getattr(settings, "ETL4LLM_ENABLED", False)) and bool(
        (getattr(settings, "ETL4LLM_API_URL", "") or "").strip()
    )
    deepseek_ocr_ok = bool(getattr(settings, "DEEPSEEK_OCR_ENABLED", False)) and bool(
        (getattr(settings, "SILICONFLOW_API_KEY", "") or "").strip()
    )
    qianfan_ocr_ok = bool(getattr(settings, "QIANFAN_OCR_ENABLED", False)) and bool(
        (getattr(settings, "QIANFAN_OCR_API_URL", "") or "").strip()
    )

    if score >= 0.8 and not is_scanned:
        if getattr(settings, "DOCLING_ENABLED", False):
            return "docling"
        if etl4llm_ok:
            return "etl4llm"
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
        if qianfan_ocr_ok:
            return "qianfan_ocr"
        if etl4llm_ok:
            return "etl4llm"
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
    if etl4llm_ok:
        return "etl4llm"
    if settings.DEEPDOC_ENABLED:
        return "deepdoc"
    if settings.MINERU_ENABLED and (settings.MINERU_API_TOKEN or settings.MINERU_LOCAL_SERVER_URL):
        return "mineru"
    if qianfan_ocr_ok:
        return "qianfan_ocr"
    if _magicpdf_available():
        return "magicpdf"
    if settings.MARKITDOWN_ENABLED:
        return "markitdown"
    return "basic"


def route_pdf_backend(
    file_path: Path,
    requested: str | None,
    *,
    quality: dict | None = None,
    sample_pages: int = 3,
    use_ocr_validation: bool | None = None,
) -> tuple[str, dict]:
    """
    Score a PDF and return (chosen_backend, quality).
    """
    from app.parsing.quality.scorer import score_pdf_quality

    use_ocr = settings.RAPIDOCR_ENABLED if use_ocr_validation is None else bool(use_ocr_validation)
    if quality is None:
        quality = score_pdf_quality(file_path, sample_pages=sample_pages, use_ocr_validation=use_ocr)
    return choose_pdf_backend(quality, requested), quality


__all__ = ["choose_pdf_backend", "route_pdf_backend", "should_attempt_pdf_fallback"]
