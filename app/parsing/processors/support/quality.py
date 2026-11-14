"""Seal, OCR and governance quality summary helpers."""

from typing import Any

from langchain_core.documents import Document

from app.parsing.processors.support.common import _log_processor_fallback
from app.rag.preprocessing.processor import GovernanceStats


def _is_table_segment_metadata(meta: dict[str, Any] | None) -> bool:
    if not isinstance(meta, dict):
        return False
    content_type = meta.get("content_type")
    doc_type = meta.get("doc_type_kwd")
    element_kind = meta.get("element_kind")
    if isinstance(content_type, str):
        content_type = content_type.strip().lower()
    if isinstance(doc_type, str):
        doc_type = doc_type.strip().lower()
    if isinstance(element_kind, str):
        element_kind = element_kind.strip().lower()
    return content_type == "table" or doc_type == "table" or element_kind == "table"


def _coerce_float(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        number = float(value)
        if number != number:
            return None
        return number
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
    content_type = meta.get("content_type")
    doc_type = meta.get("doc_type_kwd")
    if isinstance(content_type, str):
        content_type = content_type.strip().lower()
    if isinstance(doc_type, str):
        doc_type = doc_type.strip().lower()
    return content_type == "seal" or doc_type == "seal"


def _seal_candidate_from_document(doc: Document) -> dict[str, Any] | None:
    meta = doc.metadata
    if not _is_seal_segment_metadata(meta):
        return None

    raw_primary = meta.get("seal_primary")
    primary = raw_primary if isinstance(raw_primary, dict) else {}
    score = _coerce_float(primary.get("score"))
    if score is None:
        score = _coerce_float(meta.get("seal_score"))
    page = _coerce_int(meta.get("page"))
    if page is None:
        page = _coerce_int(meta.get("page_number"))
    candidate_count = _coerce_int(meta.get("seal_candidate_count"))
    if candidate_count is None:
        raw_candidates = meta.get("seal_candidates")
        candidate_count = len(raw_candidates) if isinstance(raw_candidates, list) else 1
    return {
        "text": str(primary.get("text") or meta.get("seal_text") or doc.page_content).strip(),
        "score": score,
        "kind": str(primary.get("seal_kind") or meta.get("seal_kind") or "unknown").strip() or "unknown",
        "page": page,
        "candidate_count": candidate_count,
    }


def _format_seal_summary(candidates: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not candidates:
        return None

    candidates.sort(
        key=lambda item: (
            item["score"] if item["score"] is not None else 0.0,
            item["candidate_count"],
        ),
        reverse=True,
    )
    pages = sorted({item["page"] for item in candidates if item["page"] is not None})
    primary = candidates[0]
    return {
        "detected": True,
        "count": len(candidates),
        "candidate_count_total": sum(item["candidate_count"] for item in candidates),
        "primary_text": primary["text"],
        "primary_score": primary["score"],
        "primary_kind": primary["kind"],
        "primary_page": primary["page"],
        "pages": pages,
    }


def _build_seal_summary(documents: list[Document] | None) -> dict[str, Any] | None:
    candidates: list[dict[str, Any]] = []
    for doc in documents if documents is not None else []:
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
    return max(0.0, min(1.0, confidence))


def _low_confidence_span(meta: dict[str, Any], *, text: str, confidence: float) -> dict[str, Any]:
    element_id = next(
        (meta[key] for key in ("id", "element_id", "source_element_id") if meta.get(key) is not None), None
    )
    return {
        "element_id": str(element_id) if element_id is not None else None,
        "text": str(meta.get("text") or text)[:160],
        "page": meta.get("page") or meta.get("element_page"),
        "bbox": meta.get("bbox") if isinstance(meta.get("bbox"), dict) else meta.get("element_bbox"),
        "confidence": round(float(confidence), 4),
    }


def _iter_ocr_quality_candidates(documents: list[Document] | None) -> list[tuple[dict[str, Any], str]]:
    candidates: list[tuple[dict[str, Any], str]] = []
    for doc in documents if documents is not None else []:
        meta = dict(doc.metadata)
        derived = meta.get("derived_elements")
        if isinstance(derived, list):
            for item in derived:
                if isinstance(item, dict):
                    candidates.append((dict(item), str(item.get("text") or "")))
        candidates.append((meta, doc.page_content))
    return candidates


def _build_ocr_quality_summary(
    documents: list[Document] | None,
    *,
    low_confidence_threshold: float = 0.7,
) -> dict[str, Any] | None:
    confidences: list[float] = []
    low_spans: list[dict[str, Any]] = []

    for meta, text in _iter_ocr_quality_candidates(documents):
        confidence = _ocr_confidence_from_metadata(meta)
        if confidence is None:
            continue
        confidences.append(confidence)
        if confidence < float(low_confidence_threshold):
            low_spans.append(_low_confidence_span(meta, text=text, confidence=confidence))

    if not confidences:
        return None
    avg = sum(confidences) / len(confidences)
    return {
        "schema": "mimirq.ocr_quality.v1",
        "confidence_avg": round(avg, 4),
        "confidence_min": round(min(confidences), 4),
        "span_count": len(confidences),
        "low_confidence_threshold": float(low_confidence_threshold),
        "low_confidence_count": len(low_spans),
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
        _log_processor_fallback("_build_governance_audit_metadata_patch", exc)
        density_metrics = {}
    try:
        outline_metrics = drop_if_outline_only(text, min_content_chars=0, max_heading_ratio=2.0).metrics or {}
    except Exception as exc:
        _log_processor_fallback("_build_governance_audit_metadata_patch", exc)
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
        meta = doc.metadata
        metrics = _governance_quality_from_metadata(meta)
        if metrics is None:
            metrics = _compute_governance_quality_metrics(doc.page_content)
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
        "governance_frontmatter_docs": stats.frontmatter_docs,
        "governance_frontmatter_stripped_docs": stats.frontmatter_stripped_docs,
        "governance_paragraphs_dropped": stats.paragraphs_dropped,
        "governance_references_removed_lines": stats.references_removed_lines,
        "governance_urls_changed": stats.urls_changed,
        "governance_boilerplate_removed_sections": stats.boilerplate_removed_sections,
        "governance_boilerplate_removed_lines": stats.boilerplate_removed_lines,
        "governance_images_removed": stats.images_removed,
        "governance_tables_normalized": stats.tables_normalized,
        "governance_table_rows_changed": stats.table_rows_changed,
        "governance_code_blocks_changed": stats.code_blocks_changed,
        "governance_code_lines_stripped": stats.code_lines_stripped,
        "governance_keywords_docs": stats.keywords_docs,
        "governance_keywords_total": stats.keywords_total,
        "governance_titles_docs": stats.titles_docs,
        "governance_tags_docs": stats.tags_docs,
    }
    return {key: value for key, raw in effects_map.items() if (value := _safe_governance_int(raw)) > 0}


def _clean_governance_rule_packs(rule_packs: list[str] | None) -> list[str]:
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in rule_packs if rule_packs is not None else []:
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
