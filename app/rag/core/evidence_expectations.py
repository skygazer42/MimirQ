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
    exclude_retrieval_role_prefixes: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    req = normalize_anchor_fields(list(required_fields or []))
    prefixes = [str(p or "").strip().lower() for p in (exclude_retrieval_role_prefixes or []) if str(p or "").strip()]
    if not req:
        return _empty_anchor_expectations(len(citations or []))

    missing_counts: dict[str, int] = dict.fromkeys(req, 0)
    missing_examples: list[dict[str, Any]] = []
    missing_any = 0
    considered = 0
    skipped = 0
    skipped_by_role: dict[str, int] = {}

    for item in citations or []:
        if not isinstance(item, dict):
            continue
        excluded_role = _excluded_retrieval_role(item, prefixes)
        if excluded_role is not None:
            skipped += 1
            skipped_by_role[excluded_role] = int(skipped_by_role.get(excluded_role, 0) or 0) + 1
            continue
        considered += 1
        missing_fields = _missing_anchor_fields(item, req)
        if missing_fields:
            missing_any += 1
            _increment_missing_counts(missing_counts, missing_fields)
            if len(missing_examples) < 20:
                missing_examples.append(
                    {
                        "chunk_id": item.get("chunk_id"),
                        "missing_fields": missing_fields,
                    }
                )

    return {
        "required_fields": req,
        "considered_citations": int(considered),
        "skipped_citations": int(skipped),
        "skipped_by_role": dict(skipped_by_role),
        "missing_counts": missing_counts,
        "missing_any": int(missing_any),
        "missing_examples": missing_examples,
        "passed": bool(missing_any == 0),
    }


def _empty_anchor_expectations(citation_count: int) -> dict[str, Any]:
    return {
        "required_fields": [],
        "considered_citations": int(citation_count),
        "skipped_citations": 0,
        "skipped_by_role": {},
        "missing_counts": {},
        "missing_any": 0,
        "passed": True,
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


def _increment_missing_counts(missing_counts: dict[str, int], missing_fields: list[str]) -> None:
    for field_name in missing_fields:
        missing_counts[field_name] = int(missing_counts.get(field_name, 0) or 0) + 1


__all__ = [
    "DEFAULT_EVIDENCE_ANCHOR_FIELDS",
    "normalize_anchor_fields",
    "evaluate_evidence_anchor_expectations",
]
