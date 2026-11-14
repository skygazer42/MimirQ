"""
Unified document parse-quality scoring.

This is a lightweight "quality score" used for:
- routing (manual review buckets)
- observability dashboards

It combines existing signals that are already persisted in doc metadata:
- pdf_quality.score (0..1) when available
- parsed_text_quality.density (0..1) and replacement_ratio
- pdf_quality.reading_order_score (0..1) when available
"""

from collections.abc import Mapping
from typing import Any

from app.parsing.utils.scalars import coerce_bool as _coerce_bool


def _coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (OverflowError, TypeError, ValueError):
        return None
    return None if number != number else number


def score_document_parse_quality(
    *,
    pdf_quality: Mapping[str, Any] | None,
    parsed_text_quality: Mapping[str, Any] | None,
    specialty_signals: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Return a JSON-safe payload:
    - score: float 0..1
    - components: the signals used to compute the score
    """
    pdf = {} if pdf_quality is None else pdf_quality
    text = {} if parsed_text_quality is None else parsed_text_quality
    specialty = {} if specialty_signals is None else specialty_signals
    pdf_score = _coerce_float(pdf.get("score"))
    reading_order_score = _coerce_float(pdf.get("reading_order_score"))
    density = _coerce_float(text.get("density"))
    replacement_ratio = _coerce_float(text.get("replacement_ratio"))
    seal_confidence = _coerce_float(specialty.get("seal_confidence"))
    seal_detected = _coerce_bool(specialty.get("seal_detected"))
    seal_expected = _coerce_bool(specialty.get("seal_expected"))
    seal_candidate_count = _coerce_float(specialty.get("seal_candidate_count"))

    if pdf_score is not None:
        if density is not None and reading_order_score is not None:
            base = 0.60 * pdf_score + 0.25 * density + 0.15 * reading_order_score
            source = "pdf+text+reading_order"
        elif density is not None:
            base = 0.70 * pdf_score + 0.30 * density
            source = "pdf+text"
        elif reading_order_score is not None:
            base = 0.80 * pdf_score + 0.20 * reading_order_score
            source = "pdf+reading_order"
        else:
            base = pdf_score
            source = "pdf"
    elif density is not None and reading_order_score is not None:
        base = 0.85 * density + 0.15 * reading_order_score
        source = "text+reading_order"
    elif density is not None:
        base = density
        source = "text"
    elif reading_order_score is not None:
        base = reading_order_score
        source = "reading_order"
    else:
        base = 0.0
        source = "none"

    penalty = 0.0
    if replacement_ratio is not None:
        # Replacement chars are a strong gibberish signal; cap penalty to keep score stable.
        penalty = min(0.5, max(0.0, replacement_ratio * 5.0))
    specialty_penalty = 0.0
    if seal_confidence is not None and (seal_expected is True or seal_detected is True):
        specialty_penalty = min(0.3, max(0.0, (0.6 - seal_confidence) * 0.6))
        penalty = min(0.75, penalty + specialty_penalty)

    score = base * (1.0 - penalty)
    score = max(0.0, min(1.0, score))

    return {
        "score": round(score, 3),
        "source": source,
        "components": {
            "pdf_score": (round(pdf_score, 3) if pdf_score is not None else None),
            "reading_order_score": (round(reading_order_score, 3) if reading_order_score is not None else None),
            "text_density": (round(density, 3) if density is not None else None),
            "replacement_ratio": (round(replacement_ratio, 4) if replacement_ratio is not None else None),
            "seal_confidence": (round(seal_confidence, 3) if seal_confidence is not None else None),
            "seal_detected": seal_detected,
            "seal_expected": seal_expected,
            "seal_candidate_count": (int(seal_candidate_count) if seal_candidate_count is not None else None),
            "specialty_penalty": round(specialty_penalty, 3),
            "penalty": round(penalty, 3),
        },
    }


__all__ = [
    "score_document_parse_quality",
]
