"""
PDF parsing router (auto-selection) utility.

Unified usage in:
- Preview parsing (parse-preview)
- Database parsing (documents/upload background processing)
"""

from pathlib import Path

from app.core.config import settings
from app.parsing.backends import normalize_parser_backend
from app.parsing.parsers.magic_pdf_parser import magicpdf_service_configured, resolve_magicpdf_models_dir
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
    requested_norm = normalize_parser_backend(requested)
    if requested_norm and requested_norm != "auto":
        return requested_norm
    quality = quality or {}
    score = float(quality.get("score", 0.0) or 0.0)
    text_quality_score = float(quality.get("text_quality_score", 0.0) or 0.0)
    page_count = float(quality.get("page_count", 0.0) or 0.0)
    is_scanned = bool(quality.get("is_scanned", False))

    availability = {
        "etl4llm": _etl4llm_available(),
        "deepseek_ocr": _deepseek_ocr_available(),
        "qianfan_ocr": _qianfan_ocr_available(),
        "magicpdf": _magicpdf_available(),
        "mineru": _mineru_available(),
    }

    if score >= 0.8 and not is_scanned:
        return _choose_high_quality_backend(availability)
    if _should_use_basic_for_scanned_pdf(is_scanned=is_scanned, score=score, text_quality_score=text_quality_score):
        return "basic"
    if _should_use_basic_for_small_text_pdf(
        is_scanned=is_scanned,
        score=score,
        text_quality_score=text_quality_score,
        page_count=page_count,
    ):
        return "basic"
    if is_scanned or score <= 0.5:
        return _choose_low_quality_backend(availability)
    return _choose_mid_quality_backend(availability)


def _magicpdf_available() -> bool:
    if not bool(getattr(settings, "MAGIC_PDF_ENABLED", False)):
        return False
    if magicpdf_service_configured(getattr(settings, "MAGIC_PDF_API_URL", "")):
        return True
    cli = (getattr(settings, "MAGIC_PDF_CLI", "") or "magic-pdf").strip() or "magic-pdf"
    return bool(
        resolve_cli_command(cli)
        and resolve_magicpdf_models_dir(getattr(settings, "MAGIC_PDF_MODELS_DIR", ""))
    )


def _etl4llm_available() -> bool:
    return bool(getattr(settings, "ETL4LLM_ENABLED", False)) and bool(
        (getattr(settings, "ETL4LLM_API_URL", "") or "").strip()
    )


def _deepseek_ocr_available() -> bool:
    return bool(getattr(settings, "DEEPSEEK_OCR_ENABLED", False)) and bool(
        (getattr(settings, "SILICONFLOW_API_KEY", "") or "").strip()
    )


def _qianfan_ocr_available() -> bool:
    return bool(getattr(settings, "QIANFAN_OCR_ENABLED", False)) and bool(
        (getattr(settings, "QIANFAN_OCR_API_URL", "") or "").strip()
    )


def _mineru_available() -> bool:
    return bool(settings.MINERU_ENABLED and (settings.MINERU_API_TOKEN or settings.MINERU_LOCAL_SERVER_URL))


def _should_use_basic_for_scanned_pdf(*, is_scanned: bool, score: float, text_quality_score: float) -> bool:
    return bool(is_scanned and score > 0.5 and text_quality_score >= 0.1)


def _should_use_basic_for_small_text_pdf(
    *,
    is_scanned: bool,
    score: float,
    text_quality_score: float,
    page_count: float,
) -> bool:
    return bool(not is_scanned and 0.5 < score < 0.8 and text_quality_score >= 0.3 and 0 < page_count <= 5)


def _choose_high_quality_backend(availability: dict[str, bool]) -> str:
    if getattr(settings, "DOCLING_ENABLED", False):
        return "docling"
    if availability["etl4llm"]:
        return "etl4llm"
    if settings.MARKITDOWN_ENABLED:
        return "markitdown"
    if settings.DEEPDOC_ENABLED:
        return "deepdoc"
    return "basic"


def _choose_low_quality_backend(availability: dict[str, bool]) -> str:
    if availability["mineru"]:
        return "mineru"
    if availability["deepseek_ocr"]:
        return "deepseek_ocr"
    if availability["qianfan_ocr"]:
        return "qianfan_ocr"
    if availability["etl4llm"]:
        return "etl4llm"
    if settings.DEEPDOC_ENABLED:
        return "deepdoc"
    if getattr(settings, "DOCLING_ENABLED", False):
        return "docling"
    if availability["magicpdf"]:
        return "magicpdf"
    if settings.MARKITDOWN_ENABLED:
        return "markitdown"
    return "basic"


def _choose_mid_quality_backend(availability: dict[str, bool]) -> str:
    if getattr(settings, "DOCLING_ENABLED", False):
        return "docling"
    if availability["etl4llm"]:
        return "etl4llm"
    if settings.DEEPDOC_ENABLED:
        return "deepdoc"
    if availability["mineru"]:
        return "mineru"
    if availability["qianfan_ocr"]:
        return "qianfan_ocr"
    if availability["magicpdf"]:
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
