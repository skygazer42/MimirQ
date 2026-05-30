from __future__ import annotations

import math
from typing import Any


def _clamp_unit(value: Any) -> float | None:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(num):
        return None
    return max(0.0, min(1.0, num))


def _resolve_gap_score(evidence_gap: dict[str, Any] | None) -> tuple[float, str]:
    if not isinstance(evidence_gap, dict):
        return 0.9, "unavailable"

    severity = str(evidence_gap.get("severity") or "").strip().lower()
    has_gap = bool(evidence_gap.get("has_gap"))
    if not has_gap or severity in {"", "none"}:
        return 0.9, "none"
    if severity == "high":
        return 0.2, "high"
    if severity == "medium":
        return 0.55, "medium"
    if severity == "low":
        return 0.7, "low"
    return 0.45, severity or "unknown"


def _band_for_score(score: float | None) -> str:
    if score is None:
        return "unknown"
    if score >= 0.75:
        return "high"
    if score >= 0.5:
        return "medium"
    return "low"


def compute_confidence_score(
    *,
    faithfulness_score: float | None,
    claim_total: int | None,
    claim_supported: int | None,
    evidence_gap: dict[str, Any] | None,
) -> dict[str, Any]:
    """Aggregate existing retrieval and answer-quality signals into a simple score."""

    signals: list[tuple[float, float]] = []
    reasons: list[dict[str, Any]] = []

    faithfulness = _clamp_unit(faithfulness_score)
    if faithfulness is not None:
        signals.append((faithfulness, 0.5))
        reasons.append({"signal": "faithfulness", "value": round(faithfulness, 2)})

    supported = max(0, int(claim_supported or 0))
    total = max(0, int(claim_total or 0))
    if total > 0:
        claim_coverage = _clamp_unit(supported / total)
        if claim_coverage is not None:
            signals.append((claim_coverage, 0.25))
            reasons.append({"signal": "claim_coverage", "value": round(claim_coverage, 2)})

    if signals or isinstance(evidence_gap, dict):
        gap_score, gap_state = _resolve_gap_score(evidence_gap)
        signals.append((gap_score, 0.25))
        reasons.append({"signal": "retrieval_gap", "value": gap_state})

    if not signals:
        return {"score": None, "band": "unknown", "reasons": reasons}

    total_weight = sum(weight for _, weight in signals)
    raw_score = sum(value * weight for value, weight in signals) / total_weight if total_weight else 0.0
    score = round(max(0.0, min(1.0, raw_score)), 1)
    return {"score": score, "band": _band_for_score(score), "reasons": reasons}


__all__ = ["compute_confidence_score"]
