from __future__ import annotations

from typing import Any, Iterable

MUST_RECALL_FAIL_REASON_TAXONOMY_V1 = "mimirq.contract_fail_reason.v1"


def normalize_source_keys(raw: Any) -> list[str]:
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
        s = str(v or "").strip()
        if not s:
            continue
        key = s.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
        if len(out) >= 80:
            break
    return out


def _citation_source_values(citation: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for k in (
        "table_id",
        "row_source_table",
        "document_id",
        "document_name",
        "sheet_name",
        "source",
    ):
        raw = citation.get(k)
        if raw is None:
            continue
        s = str(raw).strip()
        if not s:
            continue
        values.append(s)
    return values


def evaluate_required_source_keys(
    *,
    citations: list[dict[str, Any]] | None,
    required_source_keys: list[str] | tuple[str, ...] | None,
) -> dict[str, Any]:
    expected = normalize_source_keys(list(required_source_keys or []))
    if not expected:
        return {
            "required_source_keys": [],
            "present_source_keys": [],
            "missing_source_keys": [],
            "passed": True,
        }

    present: set[str] = set()
    display: dict[str, str] = {}
    for item in citations or []:
        if not isinstance(item, dict):
            continue
        for raw in _citation_source_values(item):
            key = raw.casefold()
            if key not in present:
                display[key] = raw
            present.add(key)

    missing: list[str] = []
    for exp in expected:
        if exp.casefold() not in present:
            missing.append(exp)

    present_out = [display[k] for k in sorted(display.keys())[:200]]
    return {
        "required_source_keys": expected,
        "present_source_keys": present_out,
        "missing_source_keys": missing,
        "passed": bool(len(missing) == 0),
    }


def build_must_recall_fail_reasons(
    *,
    citations_count: int,
    missing_source_keys: list[str] | None,
    anchor_missing_any: int,
    second_pass_attempted: bool,
    second_pass_used: bool,
) -> list[str]:
    reasons: list[str] = []
    if int(citations_count or 0) <= 0:
        reasons.append("no_citations")
    if missing_source_keys:
        reasons.append("missing_required_source_keys")
    if int(anchor_missing_any or 0) > 0:
        reasons.append("missing_required_anchor_fields")
    if second_pass_attempted and not second_pass_used:
        reasons.append("secondary_pass_no_effect")
    return reasons


__all__ = [
    "MUST_RECALL_FAIL_REASON_TAXONOMY_V1",
    "normalize_source_keys",
    "evaluate_required_source_keys",
    "build_must_recall_fail_reasons",
]
