from __future__ import annotations

from collections.abc import Iterable
from typing import Any

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
        key = str(v or "").strip()
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
) -> dict[str, Any]:
    req = normalize_anchor_fields(list(required_fields or []))
    if not req:
        return {
            "required_fields": [],
            "considered_citations": int(len(citations or [])),
            "missing_counts": {},
            "missing_any": 0,
            "passed": True,
        }

    missing_counts: dict[str, int] = dict.fromkeys(req, 0)
    missing_examples: list[dict[str, Any]] = []
    missing_any = 0
    considered = 0

    for item in citations or []:
        if not isinstance(item, dict):
            continue
        considered += 1
        miss_fields: list[str] = []
        for f in req:
            value = item.get(f)
            if value is None:
                missing_counts[f] = int(missing_counts.get(f, 0) or 0) + 1
                miss_fields.append(f)
                continue
            if isinstance(value, str) and not value.strip():
                missing_counts[f] = int(missing_counts.get(f, 0) or 0) + 1
                miss_fields.append(f)
        if miss_fields:
            missing_any += 1
            if len(missing_examples) < 20:
                missing_examples.append(
                    {
                        "chunk_id": item.get("chunk_id"),
                        "missing_fields": miss_fields,
                    }
                )

    return {
        "required_fields": req,
        "considered_citations": int(considered),
        "missing_counts": missing_counts,
        "missing_any": int(missing_any),
        "missing_examples": missing_examples,
        "passed": bool(missing_any == 0),
    }


__all__ = [
    "DEFAULT_EVIDENCE_ANCHOR_FIELDS",
    "normalize_anchor_fields",
    "evaluate_evidence_anchor_expectations",
]

