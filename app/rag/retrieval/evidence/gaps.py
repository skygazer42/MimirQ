"""Check required source keys, citation anchors and retrieval evidence gaps."""

from collections.abc import Iterable
from typing import Any

from app.rag.policy.must_recall import evaluate_required_source_keys

DEFAULT_EVIDENCE_ANCHOR_FIELDS: tuple[str, ...] = ("chunk_id", "document_id")


def normalize_anchor_fields(raw: Any) -> list[str]:
    """
    Normalize required citation anchor fields.

    Accepts:
    - CSV string
    - list/tuple/set of values
    """
    out: list[str] = []
    seen: set[str] = set()
    values: Iterable[Any]
    if isinstance(raw, str):
        values = [p.strip() for p in raw.split(",")]
    elif isinstance(raw, (list, tuple, set)):
        values = list(raw)
    else:
        values = []

    for v in values:
        key = v.strip()
        if not key:
            continue
        norm = key.lower()
        if norm in seen:
            continue
        seen.add(norm)
        out.append(norm)
        if len(out) >= 40:
            break
    return out


def evaluate_evidence_anchor_expectations(
    *,
    citations: list[dict[str, Any]] | None,
    required_fields: list[str] | tuple[str, ...] | None,
    exclude_retrieval_role_prefixes: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    req = normalize_anchor_fields(required_fields)
    items = citations if citations is not None else []
    prefixes = [
        p.strip().lower()
        for p in (exclude_retrieval_role_prefixes if exclude_retrieval_role_prefixes is not None else [])
        if p.strip()
    ]
    if not req:
        return {
            "required_fields": [],
            "considered_citations": len(items),
            "skipped_citations": 0,
            "skipped_by_role": {},
            "missing_counts": {},
            "missing_any": 0,
            "passed": True,
        }

    missing_counts: dict[str, int] = dict.fromkeys(req, 0)
    missing_examples: list[dict[str, Any]] = []
    missing_any = 0
    considered = 0
    skipped = 0
    skipped_by_role: dict[str, int] = {}

    for item in items:
        if not isinstance(item, dict):
            continue
        excluded_role = _excluded_retrieval_role(item, prefixes)
        if excluded_role is not None:
            skipped += 1
            skipped_by_role[excluded_role] = skipped_by_role.get(excluded_role, 0) + 1
            continue
        considered += 1
        missing_fields = _missing_anchor_fields(item, req)
        if missing_fields:
            missing_any += 1
            for field_name in missing_fields:
                missing_counts[field_name] += 1
            if len(missing_examples) < 20:
                missing_examples.append(
                    {
                        "chunk_id": item.get("chunk_id"),
                        "missing_fields": missing_fields,
                    }
                )

    return {
        "required_fields": req,
        "considered_citations": considered,
        "skipped_citations": skipped,
        "skipped_by_role": skipped_by_role,
        "missing_counts": missing_counts,
        "missing_any": missing_any,
        "missing_examples": missing_examples,
        "passed": missing_any == 0,
    }


def _excluded_retrieval_role(item: dict[str, Any], prefixes: list[str]) -> str | None:
    if not prefixes:
        return None
    role = str(item.get("retrieval_role") or "").strip().lower()
    if role and any(role.startswith(prefix) for prefix in prefixes):
        return role
    return None


def _missing_anchor_fields(item: dict[str, Any], required_fields: list[str]) -> list[str]:
    missing: list[str] = []
    for field_name in required_fields:
        value = item.get(field_name)
        if value is None or (isinstance(value, str) and not value.strip()):
            missing.append(field_name)
    return missing


EVIDENCE_GAP_SCHEMA_V1 = "mimirq.evidence_gap.v1"


def detect_evidence_gap(
    *,
    citations: list[dict[str, Any]] | None,
    required_source_keys: list[str] | tuple[str, ...] | None = None,
    required_anchor_fields: list[str] | tuple[str, ...] | None = None,
    min_citations: int = 1,
) -> dict[str, Any]:
    citations_norm = [c for c in (citations if citations is not None else []) if isinstance(c, dict)]
    min_citations = max(0, int(min_citations or 0))

    reason_codes: list[str] = []
    citations_total = len(citations_norm)
    if citations_total < min_citations:
        reason_codes.append("citations_below_min")

    source_eval = evaluate_required_source_keys(
        citations=citations_norm,
        required_source_keys=required_source_keys,
    )
    missing_source_keys = source_eval["missing_source_keys"]
    if missing_source_keys:
        reason_codes.append("missing_required_source_keys")

    anchor_eval = evaluate_evidence_anchor_expectations(
        citations=citations_norm,
        required_fields=DEFAULT_EVIDENCE_ANCHOR_FIELDS if required_anchor_fields is None else required_anchor_fields,
        exclude_retrieval_role_prefixes=["hierarchy_"],
    )
    anchor_missing_any = anchor_eval["missing_any"]
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
        "reason_codes": reason_codes,
        "citations_total": citations_total,
        "min_citations": min_citations,
        "required_source_keys": source_eval["required_source_keys"],
        "missing_source_keys": missing_source_keys[:40],
        "required_anchor_fields": anchor_eval["required_fields"],
        "anchor_missing_any": anchor_missing_any,
        "anchor_missing_counts": anchor_eval["missing_counts"],
    }


__all__ = [
    "DEFAULT_EVIDENCE_ANCHOR_FIELDS",
    "EVIDENCE_GAP_SCHEMA_V1",
    "normalize_anchor_fields",
    "evaluate_evidence_anchor_expectations",
    "detect_evidence_gap",
]
