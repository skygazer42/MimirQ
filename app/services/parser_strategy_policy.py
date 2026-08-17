"""
Deterministic parser strategy recommendation policy.
"""


from collections.abc import Mapping
from typing import Any


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except Exception:
        return float(default)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return int(default)
        return int(value)
    except Exception:
        return int(default)


def _norm_text(value: Any) -> str:
    return str(value or "").strip().lower()


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = _norm_text(value)
    return text in {"1", "true", "yes", "y", "on"}


def _clamp01(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return float(value)


def _is_pdf(mime: str, ext: str) -> bool:
    return mime in {"application/pdf", "application/x-pdf"} or ext == "pdf"


def _is_html(mime: str, ext: str) -> bool:
    return "html" in mime or ext in {"html", "htm"}


def _is_markdown(mime: str, ext: str) -> bool:
    return "markdown" in mime or ext in {"md", "markdown", "txt"}


def _is_spreadsheet(mime: str, ext: str) -> bool:
    if ext in {"xlsx", "xls", "csv", "tsv"}:
        return True
    return mime in {
        "text/csv",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }


def _is_image(mime: str, ext: str) -> bool:
    return mime.startswith("image/") or ext in {"png", "jpg", "jpeg", "webp", "tiff", "bmp"}


def _is_docx(mime: str, ext: str) -> bool:
    return ext in {"docx", "doc"} or mime in {
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }


def _recommend_pdf_strategy(
    *,
    ocr_ratio: float,
    image_ratio: float,
    has_tables: bool,
    seal_low_confidence: bool,
    seal_candidate_count: int,
) -> tuple[str, float, dict[str, Any], list[str]]:
    reason_codes = ["pdf_document"]
    if seal_low_confidence:
        return (
            "pdf_ocr_layout",
            0.91,
            {
                "ocr_enabled": True,
                "layout_mode": "full",
                "table_detection": True,
                "seal_review": True,
                "seal_candidate_count": int(seal_candidate_count),
            },
            [*reason_codes, "low_seal_confidence"],
        )
    if ocr_ratio >= 0.35 or image_ratio >= 0.5:
        return (
            "pdf_ocr_layout",
            0.9,
            {"ocr_enabled": True, "layout_mode": "full", "table_detection": True},
            [*reason_codes, "image_or_ocr_heavy_pdf"],
        )
    if has_tables:
        return (
            "pdf_table_aware",
            0.82,
            {"ocr_enabled": False, "layout_mode": "table_aware", "table_detection": True},
            [*reason_codes, "table_dense_pdf"],
        )
    return (
        "pdf_text_fast",
        0.78,
        {"ocr_enabled": False, "layout_mode": "fast_text", "table_detection": False},
        [*reason_codes, "text_dominant_pdf"],
    )


def _recommend_non_pdf_strategy(mime: str, ext: str) -> tuple[str, float, dict[str, Any], list[str]]:
    if _is_spreadsheet(mime, ext):
        return (
            "spreadsheet_structured",
            0.88,
            {"table_mode": "structured", "preserve_headers": True},
            ["spreadsheet_document", "table_native_format"],
        )
    if _is_html(mime, ext):
        return (
            "html_readability",
            0.8,
            {"boilerplate_removal": True, "link_density_filter": True},
            ["html_document", "dom_readability"],
        )
    if _is_markdown(mime, ext):
        return (
            "markdown_structured",
            0.75,
            {"preserve_headings": True, "preserve_code_fences": True},
            ["markdown_or_text_document"],
        )
    if _is_docx(mime, ext):
        return (
            "docx_layout",
            0.78,
            {"track_sections": True, "extract_tables": True},
            ["docx_document", "office_layout_parser"],
        )
    if _is_image(mime, ext):
        return (
            "image_ocr_vision",
            0.92,
            {"ocr_enabled": True, "vision_layout": True},
            ["image_document", "ocr_required"],
        )
    return (
        "generic_balanced",
        0.55,
        {"ocr_enabled": False, "layout_mode": "auto"},
        ["fallback_generic"],
    )


def _apply_large_document_profile(
    *,
    page_count: int,
    strategy: str,
    parser_options: dict[str, Any],
    reason_codes: list[str],
) -> None:
    if page_count >= 120 and strategy in {"pdf_ocr_layout", "pdf_table_aware", "docx_layout"}:
        reason_codes.append("large_document")
        parser_options["chunking_profile"] = "long_doc_balanced"


def recommend_parser_strategy(profile: Mapping[str, Any] | None) -> dict[str, Any]:
    """
    Recommend parser strategy by document profile.

    Input profile (best-effort):
    - mime_type, file_extension
    - page_count
    - has_tables, table_density
    - image_ratio, ocr_ratio
    """
    payload = dict(profile or {})
    mime = _norm_text(payload.get("mime_type"))
    ext = _norm_text(payload.get("file_extension")).lstrip(".")

    page_count = max(1, _safe_int(payload.get("page_count"), 1))
    table_density = _clamp01(_safe_float(payload.get("table_density"), 0.0))
    image_ratio = _clamp01(_safe_float(payload.get("image_ratio"), 0.0))
    ocr_ratio = _clamp01(_safe_float(payload.get("ocr_ratio"), 0.0))
    has_tables = _to_bool(payload.get("has_tables")) or table_density >= 0.15
    seal_expected = _to_bool(payload.get("seal_expected"))
    seal_confidence = _clamp01(_safe_float(payload.get("seal_confidence"), 0.0))
    seal_candidate_count = max(0, _safe_int(payload.get("seal_candidate_count"), 0))
    seal_low_confidence = bool(seal_expected and seal_confidence > 0.0 and seal_confidence < 0.6)

    if _is_pdf(mime, ext):
        strategy, confidence, parser_options, reason_codes = _recommend_pdf_strategy(
            ocr_ratio=ocr_ratio,
            image_ratio=image_ratio,
            has_tables=has_tables,
            seal_low_confidence=seal_low_confidence,
            seal_candidate_count=seal_candidate_count,
        )
    else:
        strategy, confidence, parser_options, reason_codes = _recommend_non_pdf_strategy(mime, ext)

    _apply_large_document_profile(
        page_count=page_count,
        strategy=strategy,
        parser_options=parser_options,
        reason_codes=reason_codes,
    )

    return {
        "schema": "mimirq.parser_strategy_recommendation.v1",
        "strategy": strategy,
        "confidence": round(_clamp01(confidence), 4),
        "reason_codes": reason_codes[:12],
        "profile": {
            "mime_type": mime or None,
            "file_extension": ext or None,
            "page_count": int(page_count),
            "table_density": round(float(table_density), 4),
            "image_ratio": round(float(image_ratio), 4),
            "ocr_ratio": round(float(ocr_ratio), 4),
            "has_tables": bool(has_tables),
            "seal_expected": bool(seal_expected),
            "seal_confidence": round(float(seal_confidence), 4) if seal_expected else None,
            "seal_candidate_count": int(seal_candidate_count),
        },
        "parser_options": parser_options,
    }


__all__ = ["recommend_parser_strategy"]
