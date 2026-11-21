"""Compute claim faithfulness and combined answer confidence signals."""

import math
from typing import Any, TypedDict

from app.rag.safety.claim_verification import split_into_claims, verify_claim_with_fallback


def compute_faithfulness_score(
    *,
    answer: str,
    evidence_text: str,
    max_claims: int = 24,
    verifier_mode: str = "token_overlap",
    verifier_enable_contradiction_check: bool = True,
    use_nli_fallback: bool = False,
    nli_provider: str | None = None,
    nli_model_name: str | None = None,
    nli_timeout_sec: float | None = None,
) -> dict[str, Any]:
    """
    Deterministic online faithfulness proxy.

    Score definition:
    - Split answer into bounded atomic claims.
    - Check each claim against evidence_text using current verifier policy.
    - faithfulness_score = supported_claims / total_claims (0..1), or None when no claims.
    """
    max_claims = max(1, int(max_claims or 0))
    raw_answer = answer.strip()
    claims = split_into_claims(raw_answer, max_claims=max_claims) if raw_answer else []
    if not claims:
        return {
            "score": None,
            "supported_claims": 0,
            "total_claims": 0,
            "unsupported_claims": [],
            "method": "claim_support_ratio",
        }

    supported = 0
    total = len(claims)
    unsupported_claims: list[str] = []
    for claim in claims:
        vr = verify_claim_with_fallback(
            claim,
            evidence_text,
            verifier_mode=verifier_mode,
            verifier_enable_contradiction_check=bool(verifier_enable_contradiction_check),
            use_nli_fallback=bool(use_nli_fallback),
            nli_provider=nli_provider,
            nli_model_name=nli_model_name,
            nli_timeout_sec=nli_timeout_sec,
        )
        if bool(vr.supported):
            supported += 1
            continue
        if len(unsupported_claims) < 16:
            unsupported_claims.append(claim[:300])

    score = round(float(supported) / float(total), 4)
    return {
        "score": score,
        "supported_claims": supported,
        "total_claims": total,
        "unsupported_claims": unsupported_claims,
        "method": "claim_support_ratio",
    }


class _ConfidenceReason(TypedDict):
    signal: str
    value: float | str


class ConfidenceScore(TypedDict):
    score: float | None
    band: str
    reasons: list[_ConfidenceReason]


def _clamp_unit(value: Any) -> float | None:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(num):
        return None
    return max(0.0, min(1.0, num))


def _resolve_gap_score(evidence_gap: dict[str, Any] | None) -> tuple[float, str]:
    if not isinstance(evidence_gap, dict):
        return 0.9, "unavailable"

    severity = evidence_gap["severity"].strip().lower()
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
) -> ConfidenceScore:
    """Aggregate existing retrieval and answer-quality signals into a simple score."""

    signals: list[tuple[float, float]] = []
    reasons: list[_ConfidenceReason] = []

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
    raw_score = sum(value * weight for value, weight in signals) / total_weight
    score = round(max(0.0, min(1.0, raw_score)), 1)
    return {"score": score, "band": _band_for_score(score), "reasons": reasons}


__all__ = ["ConfidenceScore", "compute_confidence_score", "compute_faithfulness_score"]
