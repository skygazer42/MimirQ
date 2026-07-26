"""Seal, OCR and governance quality summary helpers."""
from typing import Any

from langchain_core.documents import Document

from app.parsing.processors.support.common import _log_processor_fallback
from app.rag.preprocessing.processor import GovernanceStats


def _is_table_segment_metadata(meta: dict[str, Any] | None) -> bool:
    if not isinstance(meta, dict):
        return False
    content_type = str(meta.get("content_type") or "").strip().lower()
    doc_type = str(meta.get("doc_type_kwd") or "").strip().lower()
    element_kind = str(meta.get("element_kind") or "").strip().lower()
    return content_type == "table" or doc_type == "table" or element_kind == "table"


def _coerce_float(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        number = float(value)
        if number != number:
            return None
        return float(number)
    except (TypeError, ValueError, AttributeError):
        return None


def _coerce_int(value: Any) -> int | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        return int(value)
    except (TypeError, ValueError, AttributeError):
        return None


def _is_seal_segment_metadata(meta: dict[str, Any] | None) -> bool:
    if not isinstance(meta, dict):
        return False
    content_type = str(meta.get("content_type") or "").strip().lower()
    doc_type = str(meta.get("doc_type_kwd") or "").strip().lower()
    return content_type == "seal" or doc_type == "seal"


def _seal_primary_metadata(meta: dict[str, Any]) -> dict[str, Any]:
    primary = meta.get("seal_primary")
    return primary if isinstance(primary, dict) else {}


def _seal_segment_page(meta: dict[str, Any]) -> int | None:
    page = _coerce_int(meta.get("page"))
    return page if page is not None else _coerce_int(meta.get("page_number"))


def _seal_segment_candidate_count(meta: dict[str, Any]) -> int:
    candidate_count = _coerce_int(meta.get("seal_candidate_count"))
    if candidate_count is not None:
        return int(candidate_count)
    raw_candidates = meta.get("seal_candidates")
    return len(raw_candidates) if isinstance(raw_candidates, list) else 1


def _seal_candidate_from_document(doc: Document) -> dict[str, Any] | None:
    meta = dict(doc.metadata or {})
    if not _is_seal_segment_metadata(meta):
        return None

    primary = _seal_primary_metadata(meta)
    score = _coerce_float(primary.get("score"))
    if score is None:
        score = _coerce_float(meta.get("seal_score"))
    page = _seal_segment_page(meta)
    return {
        "text": str(primary.get("text") or meta.get("seal_text") or doc.page_content or "").strip(),
        "score": float(score) if score is not None else None,
        "kind": str(primary.get("seal_kind") or meta.get("seal_kind") or "unknown").strip() or "unknown",
        "page": int(page) if page is not None else None,
        "candidate_count": _seal_segment_candidate_count(meta),
    }


def _format_seal_summary(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not candidates:
        return None

    candidates.sort(
        key=lambda item: (
            float(item.get("score") or 0.0),
            int(item.get("candidate_count") or 0),
        ),
        reverse=True,
    )
    pages = sorted({int(item["page"]) for item in candidates if item.get("page") is not None})
    primary = candidates[0]
    return {
        "detected": True,
        "count": int(len(candidates)),
        "candidate_count_total": int(sum(int(item.get("candidate_count") or 0) for item in candidates)),
        "primary_text": str(primary.get("text") or ""),
        "primary_score": (float(primary["score"]) if primary.get("score") is not None else None),
        "primary_kind": str(primary.get("kind") or "unknown"),
        "primary_page": primary.get("page"),
        "pages": pages,
    }


def _build_seal_summary(documents: list[Document] | None) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    for doc in documents or []:
        candidate = _seal_candidate_from_document(doc)
        if candidate is not None:
            candidates.append(candidate)
    return _format_seal_summary(candidates)


def _seal_summary_to_specialty_signals(summary: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(summary, dict) or not summary:
        return None
    return {
        "seal_detected": bool(summary.get("detected")),
        "seal_expected": bool(summary.get("detected")),
        "seal_confidence": _coerce_float(summary.get("primary_score")),
        "seal_candidate_count": _coerce_int(summary.get("candidate_count_total")),
    }


def _ocr_confidence_from_metadata(meta: dict[str, Any]) -> float | None:
    confidence_value = meta.get("confidence")
    if confidence_value is None:
        confidence_value = meta.get("element_confidence")
    if confidence_value is None:
        confidence_value = meta.get("ocr_confidence")
    confidence = _coerce_float(confidence_value)
    if confidence is None:
        return None
    return max(0.0, min(1.0, float(confidence)))


def _low_confidence_span(meta: dict[str, Any], *, text: str, confidence: float) -> dict[str, Any]:
    return {
        "element_id": str(meta.get("id") or meta.get("element_id") or meta.get("source_element_id") or ""),
        "text": str(meta.get("text") or text or "")[:160],
        "page": meta.get("page") or meta.get("element_page"),
        "bbox": meta.get("bbox") if isinstance(meta.get("bbox"), dict) else meta.get("element_bbox"),
        "confidence": round(float(confidence), 4),
    }


def _iter_ocr_quality_candidates(documents: list[Document] | None) -> list[tuple[dict[str, Any], str]]:
    candidates: list[tuple[dict[str, Any], str]] = []
    for doc in documents or []:
        meta = dict(getattr(doc, "metadata", None) or {})
        derived = meta.get("derived_elements")
        if isinstance(derived, list):
            for item in derived:
                if isinstance(item, dict):
                    candidates.append((dict(item), str(item.get("text") or "")))
        candidates.append((meta, str(getattr(doc, "page_content", "") or "")))
    return candidates


def _append_ocr_quality_candidate(
    *,
    confidences: list[float],
    low_spans: list[dict[str, Any]],
    meta: dict[str, Any],
    text: str,
    low_confidence_threshold: float,
) -> None:
    confidence = _ocr_confidence_from_metadata(meta)
    if confidence is None:
        return
    confidences.append(confidence)
    if confidence < float(low_confidence_threshold):
        low_spans.append(_low_confidence_span(meta, text=text, confidence=confidence))


def _build_ocr_quality_summary(
    documents: list[Document] | None,
    *,
    low_confidence_threshold: float = 0.7,
) -> dict[str, Any] | None:
    confidences: list[float] = []
    low_spans: list[dict[str, Any]] = []

    for meta, text in _iter_ocr_quality_candidates(documents):
        _append_ocr_quality_candidate(
            confidences=confidences,
            low_spans=low_spans,
            meta=meta,
            text=text,
            low_confidence_threshold=low_confidence_threshold,
        )

    if not confidences:
        return None
    avg = sum(confidences) / max(1, len(confidences))
    return {
        "schema": "mimirq.ocr_quality.v1",
        "confidence_avg": round(float(avg), 4),
        "confidence_min": round(float(min(confidences)), 4),
        "span_count": int(len(confidences)),
        "low_confidence_threshold": float(low_confidence_threshold),
        "low_confidence_count": int(len(low_spans)),
        "low_confidence_spans": low_spans[:20],
    }


def _governance_reduction_pct(*, original_chars: int, cleaned_chars: int) -> int:
    if original_chars <= 0 or cleaned_chars < 0:
        return 0
    try:
        ratio = float((original_chars - cleaned_chars) / float(original_chars))
    except (TypeError, ValueError, AttributeError):
        ratio = 0.0
    return int(round(max(0.0, min(1.0, ratio)) * 100.0))


def _safe_governance_int(raw: object) -> int:
    try:
        if raw is None or isinstance(raw, bool):
            return 0
        return int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError, AttributeError):
        return 0


def _governance_quality_from_metadata(meta: dict[str, Any]) -> tuple[int, int, int, int, int] | None:
    quality = meta.get("governance_quality")
    if not isinstance(quality, dict):
        return None
    return (
        _safe_governance_int(quality.get("chars_non_space")),
        _safe_governance_int(quality.get("chars_alnum_cjk")),
        _safe_governance_int(quality.get("lines_total")),
        _safe_governance_int(quality.get("lines_outline")),
        _safe_governance_int(quality.get("content_chars")),
    )


def _compute_governance_quality_metrics(text: str) -> tuple[int, int, int, int, int]:
    from app.rag.preprocessing.quality_filters import drop_if_low_density, drop_if_outline_only

    try:
        density_metrics = drop_if_low_density(text, threshold=-1.0).metrics or {}
    except Exception as exc:
        _log_processor_fallback('_build_governance_audit_metadata_patch', exc)
        density_metrics = {}
    try:
        outline_metrics = drop_if_outline_only(text, min_content_chars=0, max_heading_ratio=2.0).metrics or {}
    except Exception as exc:
        _log_processor_fallback('_build_governance_audit_metadata_patch', exc)
        outline_metrics = {}

    return (
        _safe_governance_int(density_metrics.get("chars_non_space")),
        _safe_governance_int(density_metrics.get("chars_alnum_cjk")),
        _safe_governance_int(outline_metrics.get("lines_total")),
        _safe_governance_int(outline_metrics.get("lines_outline")),
        _safe_governance_int(outline_metrics.get("content_chars")),
    )


def _aggregate_governance_quality(source_items: list[Document]) -> dict[str, Any]:
    chars_non_space = 0
    chars_alnum_cjk = 0
    lines_total = 0
    lines_outline = 0
    content_chars = 0

    for doc in source_items:
        meta = doc.metadata if isinstance(getattr(doc, "metadata", None), dict) else {}
        metrics = _governance_quality_from_metadata(meta)
        if metrics is None:
            metrics = _compute_governance_quality_metrics(doc.page_content or "")
        chars_non_space += metrics[0]
        chars_alnum_cjk += metrics[1]
        lines_total += metrics[2]
        lines_outline += metrics[3]
        content_chars += metrics[4]

    density = float(chars_alnum_cjk / max(1, chars_non_space)) if chars_non_space > 0 else 0.0
    heading_ratio = float(lines_outline / max(1, lines_total)) if lines_total > 0 else 0.0
    return {
        "density": round(float(max(0.0, min(1.0, density))), 6),
        "chars_non_space": int(max(0, chars_non_space)),
        "chars_alnum_cjk": int(max(0, chars_alnum_cjk)),
        "heading_ratio": round(float(max(0.0, min(1.0, heading_ratio))), 6),
        "lines_total": int(max(0, lines_total)),
        "lines_outline": int(max(0, lines_outline)),
        "content_chars": int(max(0, content_chars)),
    }


def _positive_governance_counts(stats: GovernanceStats) -> dict[str, int]:
    effects_map = {
        "governance_frontmatter_docs": getattr(stats, "frontmatter_docs", 0),
        "governance_frontmatter_stripped_docs": getattr(stats, "frontmatter_stripped_docs", 0),
        "governance_paragraphs_dropped": getattr(stats, "paragraphs_dropped", 0),
        "governance_references_removed_lines": getattr(stats, "references_removed_lines", 0),
        "governance_urls_changed": getattr(stats, "urls_changed", 0),
        "governance_boilerplate_removed_sections": getattr(stats, "boilerplate_removed_sections", 0),
        "governance_boilerplate_removed_lines": getattr(stats, "boilerplate_removed_lines", 0),
        "governance_images_removed": getattr(stats, "images_removed", 0),
        "governance_tables_normalized": getattr(stats, "tables_normalized", 0),
        "governance_table_rows_changed": getattr(stats, "table_rows_changed", 0),
        "governance_code_blocks_changed": getattr(stats, "code_blocks_changed", 0),
        "governance_code_lines_stripped": getattr(stats, "code_lines_stripped", 0),
        "governance_keywords_docs": getattr(stats, "keywords_docs", 0),
        "governance_keywords_total": getattr(stats, "keywords_total", 0),
        "governance_titles_docs": getattr(stats, "titles_docs", 0),
        "governance_tags_docs": getattr(stats, "tags_docs", 0),
    }
    return {key: value for key, raw in effects_map.items() if (value := _safe_governance_int(raw)) > 0}


def _positive_string_count_map(raw_counts: Any) -> dict[str, int] | None:
    if not isinstance(raw_counts, dict) or not raw_counts:
        return None
    out: dict[str, int] = {}
    for raw_key, raw_value in raw_counts.items():
        if raw_key is None:
            continue
        key = str(raw_key).strip()
        value = _safe_governance_int(raw_value)
        if key and value > 0:
            out[key] = value
    return out or None


def _string_count_map(raw_counts: Any) -> dict[str, int] | None:
    if not isinstance(raw_counts, dict) or not raw_counts:
        return None
    return {str(key): int(value) for key, value in raw_counts.items()}


def _clean_governance_rule_packs(rule_packs: list[str] | None) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in rule_packs or []:
        if not isinstance(raw, str):
            continue
        key = raw.strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        cleaned.append(key[:64])
        if len(cleaned) >= 20:
            break
    return cleaned
