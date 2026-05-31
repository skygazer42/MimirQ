"""
PDF quality scorer to decide parsing routing.

Scoring dimensions (sample first 3 pages):
- Text extraction quality: volume, readability, OCR noise
- Format consistency: fonts, line spacing, paragraph structure
- Table integrity: detection rate, alignment
- Reading order: geometric consistency of observed word flow

Final score 0-1; higher is cleaner. Low scores prefer OCR/structured flow.
"""

import re
from pathlib import Path
from typing import Any

import pdfplumber  # type: ignore

from app.parsing.quality.ocr_validator import rapid_ocr_service
from app.parsing.quality.reading_order import score_pdfplumber_reading_order
from app.rag.core.logging import get_logger

logger = get_logger("parsing.quality.scorer")
_PARSING_QUALITY_FALLBACK_LOG_MESSAGE = "Ignoring non-critical parsing quality fallback failure: %s"


def score_pdf_quality(
    file_path: Path,
    sample_pages: int = 3,
    use_ocr_validation: bool = False
) -> dict[str, Any]:
    """
    Lightweight scoring for a PDF (sample first sample_pages).

    Dimensions:
    - Text quality (50%): volume, readability, OCR noise, scan detection
    - Format consistency (30%): font diversity, line spacing variance, structure
    - Table integrity (20%): detection rate, alignment

    Returns:
    - score: final score 0-1 (higher = cleaner)
    - text_quality_score: text quality score (0-1)
    - format_consistency_score: format consistency score (0-1)
    - table_quality_score: table integrity score (0-1)
    - is_scanned: whether scanned
    - page_count: total pages

    Heuristic: score >= 0.8 => clean; <= 0.5 => likely scanned/handwritten.

    Args:
        file_path: PDF path.
        sample_pages: Number of sampled pages (default 3).
        use_ocr_validation: Whether to enable RapidOCR validation.
    """
    page_count = 0
    text_quality_score = 0.0
    format_consistency_score = 0.0
    table_quality_score = 0.0
    reading_order_score = 1.0
    is_scanned = False
    preprocess_info: dict[str, Any] = {
        "skew_angle": None,
        "orientation": 0,
        "watermark_detected": False,
        "watermark_regions": [],
        "geometric_distortion": None,
    }

    try:
        with pdfplumber.open(str(file_path)) as pdf:
            page_count = len(pdf.pages)
            sampled_pages = max(1, min(sample_pages, page_count))
            pages_data = pdf.pages[:sampled_pages]

            # Dimension 1: text extraction quality (50%).
            text_quality_score, is_scanned = _score_text_quality(
                pages_data, file_path, use_ocr_validation
            )

            # Dimension 2: format consistency (30%).
            format_consistency_score = _score_format_consistency(pages_data)

            # Dimension 3: table integrity (20%).
            table_quality_score = _score_table_quality(pages_data)

            # Dimension 4: reading-order consistency (15%).
            reading_order_score = float((score_pdfplumber_reading_order(pages_data) or {}).get("score") or 1.0)

    except Exception as e:
        logger.warning("PDF quality scoring failed: %s", e)
        # Return low scores on failure.
        text_quality_score = 0.0
        format_consistency_score = 0.0
        table_quality_score = 0.0
        reading_order_score = 1.0
    finally:
        try:
            preprocess_info.update(_detect_preprocess_info(file_path, sample_pages=sample_pages))
        except Exception as exc:
            logger.debug(_PARSING_QUALITY_FALLBACK_LOG_MESSAGE, exc)

    # Weighted sum: text 40% + format 25% + table 20% + reading order 15%.
    final_score = (
        0.40 * text_quality_score +
        0.25 * format_consistency_score +
        0.20 * table_quality_score +
        0.15 * reading_order_score
    )
    final_score = max(0.0, min(1.0, final_score))

    return {
        "score": round(final_score, 3),
        "text_quality_score": round(text_quality_score, 3),
        "format_consistency_score": round(format_consistency_score, 3),
        "table_quality_score": round(table_quality_score, 3),
        "reading_order_score": round(reading_order_score, 3),
        "is_scanned": is_scanned,
        "page_count": float(page_count),
        "preprocess_info": preprocess_info,
    }


def _detect_preprocess_info(file_path: Path, *, sample_pages: int) -> dict[str, Any]:
    """
    Best-effort PDF preprocess hints used by routing/diagnostics.

    This is intentionally lightweight and does not run model inference.
    """
    info: dict[str, Any] = {
        "skew_angle": None,
        "orientation": 0,
        "watermark_detected": False,
        "watermark_regions": [],
        "geometric_distortion": None,
    }

    try:
        import fitz  # PyMuPDF
    except Exception:
        return info

    doc = None
    try:
        doc = fitz.open(str(file_path))
        n = int(getattr(doc, "page_count", 0) or 0)
        k = max(1, min(int(sample_pages or 0) or 1, n if n > 0 else 1))

        rot_counts: dict[int, int] = {}
        watermark_annots = 0

        for i in range(k):
            page = doc.load_page(i)
            rot = int(getattr(page, "rotation", 0) or 0) % 360
            rot_counts[int(rot)] = rot_counts.get(int(rot), 0) + 1

            try:
                annots = list(page.annots() or [])
            except Exception:
                annots = []
            for annot in annots:
                try:
                    typ = getattr(annot, "type", None)
                    name = ""
                    if isinstance(typ, (tuple, list)) and len(typ) >= 2:
                        name = str(typ[1] or "")
                    meta = getattr(annot, "info", None) or {}
                    subject = str((meta or {}).get("subject") or (meta or {}).get("title") or "")
                    hint = f"{name} {subject}".lower()
                    if "watermark" in hint or name.strip().lower() in {"watermark", "stamp"}:
                        watermark_annots += 1
                except Exception:
                    continue

        if rot_counts:
            orientation = max(rot_counts.items(), key=lambda kv: kv[1])[0]
        else:
            orientation = 0
        info["orientation"] = int(orientation)
        info["rotation_counts"] = {str(k): int(v) for k, v in sorted(rot_counts.items(), key=lambda kv: kv[0])}
        info["watermark_annots"] = int(watermark_annots)
        info["watermark_detected"] = bool(watermark_annots > 0)
        return info
    except Exception:
        return info
    finally:
        try:
            if doc is not None:
                doc.close()
        except Exception as exc:
            logger.debug(_PARSING_QUALITY_FALLBACK_LOG_MESSAGE, exc)


def _score_text_quality(
    pages: list,
    file_path: Path,
    use_ocr_validation: bool
) -> tuple[float, bool]:
    """
    Evaluate text extraction quality (0-1).
    Metrics: text density, noise ratio, readability, scan detection.
    """
    total_text_chars = 0
    total_expected_chars = 0
    noise_chars = 0
    is_scanned = False

    for page in pages:
        text = page.extract_text() or ""
        total_text_chars += len(text)
        
        # Noise estimate: non-printable chars + repeated symbols.
        noise_chars += len(re.findall(r"[^\x20-\x7E\u4e00-\u9fff]", text))
        noise_chars += len(re.findall(r"[#@]{4,}|[.,]{6,}|_{10,}", text))
        
        # Expected char count (rough): by page size.
        total_expected_chars += 2400  # Assume ~2400 chars per page (80x30).

    # Text density.
    text_density = total_text_chars / max(1, total_expected_chars)
    text_density = min(1.0, text_density)  # Cap at 1.
    
    # Noise ratio.
    noise_ratio = noise_chars / max(1, total_text_chars)
    clean_ratio = max(0.0, 1.0 - noise_ratio)
    
    # Base score: density 70% + cleanliness 30%.
    score = 0.70 * text_density + 0.30 * clean_ratio

    # OCR validation: trigger when text is sparse.
    if use_ocr_validation and (text_density < 0.3 or total_text_chars < 200 * len(pages)):
        try:
            logger.info("RapidOCR validation enabled for scanned detection")
            _, ocr_chars = rapid_ocr_service.ocr_pdf_pages(
                file_path,
                max_pages=min(2, len(pages))
            )
            
            ocr_gain = (ocr_chars - total_text_chars) / max(1, total_text_chars)
            
            if ocr_gain > 0.5:
                # OCR gain >50% => scanned.
                is_scanned = True
                score *= 0.4
                logger.info("Detected scanned PDF (ocr_gain=%.2f)", ocr_gain)
            elif ocr_gain > 0.1:
                # OCR gain >10% => partial scan.
                score *= 0.7
                logger.info("Detected mixed/partial scan (ocr_gain=%.2f)", ocr_gain)
        except Exception as e:
            logger.warning("RapidOCR validation failed: %s", e)

    # Very low text => treat as scanned.
    if total_text_chars < 500 and len(pages) >= 2:
        is_scanned = True
        score *= 0.5

    return max(0.0, min(1.0, score)), is_scanned


def _score_format_consistency(pages: list) -> float:
    """
    Evaluate format consistency (0-1).
    Metrics: font diversity, line spacing variance, paragraph structure.
    """
    font_sizes = []
    line_heights = []
    paragraph_count = 0
    
    for page in pages:
        try:
            # Extract character metadata.
            chars = page.chars or []
            if chars:
                # Font sizes.
                font_sizes.extend([c.get("size", 0) for c in chars if c.get("size")])
                
                # Line heights (group by y).
                y_coords = sorted({c.get("top", 0) for c in chars})
                if len(y_coords) > 1:
                    heights = [y_coords[i+1] - y_coords[i] for i in range(len(y_coords)-1)]
                    line_heights.extend(heights)
            
            # Paragraph count (split by blank lines).
            text = page.extract_text() or ""
            paragraph_count += len(re.findall(r"\n\n+", text)) + 1
        except Exception as exc:
            logger.debug(_PARSING_QUALITY_FALLBACK_LOG_MESSAGE, exc)

    if not font_sizes:
        # No font info => default to mid score.
        return 0.5

    # Font size consistency (lower std is better).
    import statistics
    try:
        font_std = statistics.stdev(font_sizes) if len(font_sizes) > 1 else 0
        font_consistency = max(0.0, 1.0 - min(1.0, font_std / 10.0))  # Normalize.
    except Exception:
        font_consistency = 0.5

    # Line height consistency.
    try:
        if line_heights:
            line_std = statistics.stdev(line_heights) if len(line_heights) > 1 else 0
            line_consistency = max(0.0, 1.0 - min(1.0, line_std / 20.0))
        else:
            line_consistency = 0.5
    except Exception:
        line_consistency = 0.5

    # Paragraph structure (separators => more regular).
    para_per_page = paragraph_count / max(1, len(pages))
    para_score = min(1.0, para_per_page / 5.0)  # Assume 5 paragraphs/page ideal.

    # Composite: font 40% + line height 40% + paragraph 20%.
    score = 0.40 * font_consistency + 0.40 * line_consistency + 0.20 * para_score
    return max(0.0, min(1.0, score))


def _score_table_quality(pages: list) -> float:
    """
    Evaluate table integrity (0-1).
    Metrics: detection rate, cell alignment.
    """
    total_tables = 0
    well_formed_tables = 0
    
    for page in pages:
        try:
            tables = page.find_tables() or []
            total_tables += len(tables)
            
            for table in tables:
                # Table rows/cols.
                rows = len(table.rows) if hasattr(table, "rows") and table.rows else 0
                cells = table.cells if hasattr(table, "cells") and table.cells else []
                
                # Consider "complete": at least 2x2 and reasonable cell count.
                if rows >= 2 and len(cells) >= 4:
                    well_formed_tables += 1
        except Exception as exc:
            logger.debug(_PARSING_QUALITY_FALLBACK_LOG_MESSAGE, exc)

    if total_tables == 0:
        # No tables => full score.
        return 1.0

    # Proportion of well-formed tables.
    table_ratio = well_formed_tables / max(1, total_tables)
    return max(0.0, min(1.0, table_ratio))
