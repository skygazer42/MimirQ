from __future__ import annotations

from typing import Any


def classify_pdf_page_density(
    page_char_counts: list[int | float],
    *,
    scan_page_max_chars: int = 50,
    text_page_min_chars: int = 200,
    scan_ratio_threshold: float = 0.7,
    mixed_ratio_threshold: float = 0.2,
) -> dict[str, Any]:
    page_types: list[str] = []
    scan_pages = 0
    low_density_pages = 0
    text_pages = 0

    for raw in page_char_counts or []:
        try:
            chars = int(raw or 0)
        except Exception:
            chars = 0
        if chars < int(scan_page_max_chars):
            page_types.append("scan")
            scan_pages += 1
        elif chars > int(text_page_min_chars):
            page_types.append("text")
            text_pages += 1
        else:
            page_types.append("low_density")
            low_density_pages += 1

    total = len(page_types)
    scan_ratio = 0.0 if total <= 0 else round(scan_pages / float(total), 4)
    if scan_ratio >= float(scan_ratio_threshold):
        pdf_type = "SCAN"
    elif scan_ratio > float(mixed_ratio_threshold):
        pdf_type = "MIXED"
    else:
        pdf_type = "TEXT"

    return {
        "schema": "mimirq.pre_poc.pdf_page_classifier.v1",
        "page_types": page_types,
        "summary": {
            "page_count": int(total),
            "scan_pages": int(scan_pages),
            "low_density_pages": int(low_density_pages),
            "text_pages": int(text_pages),
            "scan_ratio": scan_ratio,
            "pdf_type": pdf_type,
        },
    }


__all__ = ["classify_pdf_page_density"]
