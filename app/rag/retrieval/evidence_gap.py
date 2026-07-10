
from typing import Any

from app.rag.core.evidence_expectations import (
    DEFAULT_EVIDENCE_ANCHOR_FIELDS,
    evaluate_evidence_anchor_expectations,
    normalize_anchor_fields,
)
from app.rag.policy.must_recall import evaluate_required_source_keys, normalize_source_keys

EVIDENCE_GAP_SCHEMA_V1 = "mimirq.evidence_gap.v1"


def detect_evidence_gap(
    *,
    citations: list[dict[str, Any]] | None,
    required_source_keys: list[str] | tuple[str, ...] | None = None,
    required_anchor_fields: list[str] | tuple[str, ...] | None = None,
    min_citations: int = 1,
) -> dict[str, Any]:
    req_source_keys = normalize_source_keys(list(required_source_keys or []))
    req_anchor_fields = normalize_anchor_fields(
        list(required_anchor_fields or list(DEFAULT_EVIDENCE_ANCHOR_FIELDS))
    )
    citations_norm = [c for c in (citations or []) if isinstance(c, dict)]

    reason_codes: list[str] = []
    citations_total = int(len(citations_norm))
    if citations_total < max(0, int(min_citations or 0)):
        reason_codes.append("citations_below_min")

    source_eval = evaluate_required_source_keys(
        citations=citations_norm,
        required_source_keys=req_source_keys,
    )
    missing_source_keys = [str(v) for v in (source_eval.get("missing_source_keys") or []) if str(v).strip()]
    if missing_source_keys:
        reason_codes.append("missing_required_source_keys")

    anchor_eval = evaluate_evidence_anchor_expectations(
        citations=citations_norm,
        required_fields=req_anchor_fields,
        exclude_retrieval_role_prefixes=["hierarchy_"],
    )
    anchor_missing_any = int(anchor_eval.get("missing_any") or 0)
    if anchor_missing_any > 0:
        reason_codes.append("missing_required_anchor_fields")

    has_gap = bool(reason_codes)
    severity = "none"
    if "citations_below_min" in reason_codes:
        severity = "high"
    elif missing_source_keys or anchor_missing_any > 0:
        severity = "medium"

    return {
        "schema": EVIDENCE_GAP_SCHEMA_V1,
        "has_gap": has_gap,
        "severity": severity,
        "reason_codes": list(reason_codes),
        "citations_total": citations_total,
        "min_citations": max(0, int(min_citations or 0)),
        "required_source_keys": req_source_keys,
        "missing_source_keys": missing_source_keys[:40],
        "required_anchor_fields": req_anchor_fields,
        "anchor_missing_any": anchor_missing_any,
        "anchor_missing_counts": dict(anchor_eval.get("missing_counts") or {}),
    }


__all__ = [
    "EVIDENCE_GAP_SCHEMA_V1",
    "detect_evidence_gap",
]
