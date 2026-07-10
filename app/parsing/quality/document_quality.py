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


def _coerce_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        if isinstance(value, bool):
            return float(int(value))
        f = float(value)
        if f != f:  # NaN
            return None
        return f
    except Exception:
        return None


def _coerce_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return None


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
    pdf_score = _coerce_float((pdf_quality or {}).get("score"))
    reading_order_score = _coerce_float((pdf_quality or {}).get("reading_order_score"))
    density = _coerce_float((parsed_text_quality or {}).get("density"))
    replacement_ratio = _coerce_float((parsed_text_quality or {}).get("replacement_ratio"))
    specialty = specialty_signals or {}
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

    pen = 0.0
    if replacement_ratio is not None:
        # Replacement chars are a strong gibberish signal; cap penalty to keep score stable.
        pen = min(0.5, max(0.0, float(replacement_ratio) * 5.0))
    specialty_penalty = 0.0
    if seal_confidence is not None and (seal_expected is True or seal_detected is True):
        specialty_penalty = min(0.3, max(0.0, (0.6 - float(seal_confidence)) * 0.6))
        pen = min(0.75, pen + specialty_penalty)

    score = float(base) * (1.0 - float(pen))
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
            "penalty": round(pen, 3),
        },
    }


__all__ = [
    "score_document_parse_quality",
]
