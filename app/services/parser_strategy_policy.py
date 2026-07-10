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

    reason_codes: list[str] = []
    strategy: str
    confidence: float
    parser_options: dict[str, Any]

    if _is_pdf(mime, ext):
        reason_codes.append("pdf_document")
        if seal_low_confidence:
            strategy = "pdf_ocr_layout"
            reason_codes.append("low_seal_confidence")
            confidence = 0.91
            parser_options = {
                "ocr_enabled": True,
                "layout_mode": "full",
                "table_detection": True,
                "seal_review": True,
                "seal_candidate_count": int(seal_candidate_count),
            }
        elif ocr_ratio >= 0.35 or image_ratio >= 0.5:
            strategy = "pdf_ocr_layout"
            reason_codes.append("image_or_ocr_heavy_pdf")
            confidence = 0.9
            parser_options = {"ocr_enabled": True, "layout_mode": "full", "table_detection": True}
        elif has_tables:
            strategy = "pdf_table_aware"
            reason_codes.append("table_dense_pdf")
            confidence = 0.82
            parser_options = {"ocr_enabled": False, "layout_mode": "table_aware", "table_detection": True}
        else:
            strategy = "pdf_text_fast"
            reason_codes.append("text_dominant_pdf")
            confidence = 0.78
            parser_options = {"ocr_enabled": False, "layout_mode": "fast_text", "table_detection": False}
    elif _is_spreadsheet(mime, ext):
        strategy = "spreadsheet_structured"
        reason_codes.extend(["spreadsheet_document", "table_native_format"])
        confidence = 0.88
        parser_options = {"table_mode": "structured", "preserve_headers": True}
    elif _is_html(mime, ext):
        strategy = "html_readability"
        reason_codes.extend(["html_document", "dom_readability"])
        confidence = 0.8
        parser_options = {"boilerplate_removal": True, "link_density_filter": True}
    elif _is_markdown(mime, ext):
        strategy = "markdown_structured"
        reason_codes.extend(["markdown_or_text_document"])
        confidence = 0.75
        parser_options = {"preserve_headings": True, "preserve_code_fences": True}
    elif _is_docx(mime, ext):
        strategy = "docx_layout"
        reason_codes.extend(["docx_document", "office_layout_parser"])
        confidence = 0.78
        parser_options = {"track_sections": True, "extract_tables": True}
    elif _is_image(mime, ext):
        strategy = "image_ocr_vision"
        reason_codes.extend(["image_document", "ocr_required"])
        confidence = 0.92
        parser_options = {"ocr_enabled": True, "vision_layout": True}
    else:
        strategy = "generic_balanced"
        reason_codes.append("fallback_generic")
        confidence = 0.55
        parser_options = {"ocr_enabled": False, "layout_mode": "auto"}

    if page_count >= 120 and strategy in {"pdf_ocr_layout", "pdf_table_aware", "docx_layout"}:
        reason_codes.append("large_document")
        parser_options["chunking_profile"] = "long_doc_balanced"

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
