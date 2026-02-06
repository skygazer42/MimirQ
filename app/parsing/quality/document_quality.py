"""
Unified document parse-quality scoring.

This is a lightweight "quality score" used for:
- routing (manual review buckets)
- observability dashboards

It combines existing signals that are already persisted in doc metadata:
- pdf_quality.score (0..1) when available
- parsed_text_quality.density (0..1) and replacement_ratio
"""

from __future__ import annotations

from typing import Any, Mapping


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


def score_document_parse_quality(
    *,
    pdf_quality: Mapping[str, Any] | None,
    parsed_text_quality: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """
    Return a JSON-safe payload:
    - score: float 0..1
    - components: the signals used to compute the score
    """
    pdf_score = _coerce_float((pdf_quality or {}).get("score"))
    density = _coerce_float((parsed_text_quality or {}).get("density"))
    replacement_ratio = _coerce_float((parsed_text_quality or {}).get("replacement_ratio"))

    if pdf_score is not None:
        base = pdf_score if density is None else (0.70 * pdf_score + 0.30 * density)
        source = "pdf+text" if density is not None else "pdf"
    elif density is not None:
        base = density
        source = "text"
    else:
        base = 0.0
        source = "none"

    pen = 0.0
    if replacement_ratio is not None:
        # Replacement chars are a strong gibberish signal; cap penalty to keep score stable.
        pen = min(0.5, max(0.0, float(replacement_ratio) * 5.0))

    score = float(base) * (1.0 - float(pen))
    score = max(0.0, min(1.0, score))

    return {
        "score": round(score, 3),
        "source": source,
        "components": {
            "pdf_score": (round(pdf_score, 3) if pdf_score is not None else None),
            "text_density": (round(density, 3) if density is not None else None),
            "replacement_ratio": (round(replacement_ratio, 4) if replacement_ratio is not None else None),
            "penalty": round(pen, 3),
        },
    }


__all__ = [
    "score_document_parse_quality",
]

