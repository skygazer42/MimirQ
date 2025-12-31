"""
PDF 解析分流（自动选择）工具。

统一复用在：
- 预览解析（parse-preview）
- 入库解析（documents/upload 后台处理）
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional, Tuple

from app.core.config import settings


def choose_pdf_backend(quality: Optional[Dict], requested: Optional[str]) -> str:
    """
    Choose a PDF parser backend based on quality scoring and user request.

    Rules:
    - requested is set and not "auto" -> honor requested.
    - score >= 0.8 and not scanned -> prefer MarkItDown/basic.
    - scanned or score <= 0.5 -> prefer MinerU/DeepDoc, fallback MarkItDown/basic.
    - mid range -> prefer DeepDoc/MinerU, fallback MarkItDown/basic.
    """
    requested_norm = (requested or "").strip().lower()
    if requested_norm and requested_norm != "auto":
        return requested_norm

    quality = quality or {}
    score = float(quality.get("score", 0.0) or 0.0)
    is_scanned = bool(quality.get("is_scanned", False))

    if score >= 0.8 and not is_scanned:
        if settings.MARKITDOWN_ENABLED:
            return "markitdown"
        return "basic"

    if is_scanned or score <= 0.5:
        if settings.MINERU_ENABLED and (settings.MINERU_API_TOKEN or settings.MINERU_LOCAL_SERVER_URL):
            return "mineru"
        if settings.DEEPDOC_ENABLED:
            return "deepdoc"
        if settings.MARKITDOWN_ENABLED:
            return "markitdown"
        return "basic"

    if settings.DEEPDOC_ENABLED:
        return "deepdoc"
    if settings.MINERU_ENABLED and (settings.MINERU_API_TOKEN or settings.MINERU_LOCAL_SERVER_URL):
        return "mineru"
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
