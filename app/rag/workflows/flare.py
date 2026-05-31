from __future__ import annotations

from typing import Any

from app.rag.core.confidence import compute_confidence_score

FLARE_REFINEMENT_SCHEMA_V1 = "mimirq.flare_refinement.v1"


def _resolve_confidence(
    *,
    confidence_score: float | None,
    faithfulness_score: float | None,
    claim_total: int | None,
    claim_supported: int | None,
    evidence_gap: dict[str, Any] | None,
) -> dict[str, Any]:
    if confidence_score is not None:
        try:
            score = max(0.0, min(1.0, float(confidence_score)))
        except (TypeError, ValueError):
            score = None
        if score is not None:
            if score >= 0.75:
                band = "high"
            elif score >= 0.5:
                band = "medium"
            else:
                band = "low"
            return {"score": round(score, 4), "band": band, "reasons": [{"signal": "explicit_confidence", "value": score}]}

    return compute_confidence_score(
        faithfulness_score=faithfulness_score,
        claim_total=claim_total,
        claim_supported=claim_supported,
        evidence_gap=evidence_gap,
    )


def run_flare_refinement(
    *,
    question: str,
    draft_answer: str,
    evidence_gap: dict[str, Any] | None = None,
    confidence_score: float | None = None,
    faithfulness_score: float | None = None,
    claim_total: int | None = None,
    claim_supported: int | None = None,
) -> dict[str, Any]:
    del draft_answer  # Reserved for future paragraph-level rewrite logic.

    confidence = _resolve_confidence(
        confidence_score=confidence_score,
        faithfulness_score=faithfulness_score,
        claim_total=claim_total,
        claim_supported=claim_supported,
        evidence_gap=evidence_gap,
    )
    score = confidence.get("score")
    need_retrieval = bool(score is not None and float(score) < 0.5)

    reason_codes: list[str] = []
    if need_retrieval:
        reason_codes.append("low_confidence")

    return {
        "schema": FLARE_REFINEMENT_SCHEMA_V1,
        "granularity": "paragraph",
        "need_retrieval": need_retrieval,
        "rewrite_query": str(question or "").strip() or None if need_retrieval else None,
        "confidence_score": score,
        "confidence_band": confidence.get("band"),
        "confidence_reasons": list(confidence.get("reasons") or []),
        "reason_codes": reason_codes,
    }


__all__ = ["FLARE_REFINEMENT_SCHEMA_V1", "run_flare_refinement"]
