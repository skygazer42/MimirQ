
from collections.abc import Iterable
from typing import Any

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


def _collect_present_source_keys(
    citations: list[dict[str, Any]] | None,
) -> tuple[set[str], dict[str, str]]:
    present: set[str] = set()
    display: dict[str, str] = {}
    for item in citations or []:
        if not isinstance(item, dict):
            continue
        for raw in _citation_source_values(item):
            folded = raw.casefold()
            if folded not in present:
                display[folded] = raw
            present.add(folded)
    return present, display


def _match_required_source_keys(
    expected: list[str],
    present: set[str],
    display: dict[str, str],
) -> tuple[list[str], list[str], dict[str, str]]:
    missing: list[str] = []
    matched: list[str] = []
    matched_by_required: dict[str, str] = {}
    for exp in expected:
        folded = exp.casefold()
        if folded not in present:
            missing.append(exp)
            continue
        matched_display = display.get(folded) or exp
        matched.append(matched_display)
        matched_by_required[exp] = matched_display
    return missing, matched, matched_by_required


def evaluate_required_source_keys(
    *,
    citations: list[dict[str, Any]] | None,
    required_source_keys: list[str] | tuple[str, ...] | None,
) -> dict[str, Any]:
    expected = normalize_source_keys(list(required_source_keys or []))
    if not expected:
        return {
            "required_source_keys": [],
            "required_source_keys_count": 0,
            "present_source_keys": [],
            "matched_source_keys": [],
            "matched_by_required_source_key": {},
            "missing_source_keys": [],
            "matched_source_keys_count": 0,
            "missing_source_keys_count": 0,
            "coverage_ratio": 1.0,
            "passed": True,
        }

    present, display = _collect_present_source_keys(citations)
    missing, matched, matched_by_required = _match_required_source_keys(expected, present, display)

    present_out = [display[k] for k in sorted(display.keys())[:200]]
    required_n = int(len(expected))
    missing_n = int(len(missing))
    matched_n = max(0, required_n - missing_n)
    coverage_ratio = float(matched_n / required_n) if required_n > 0 else 1.0
    return {
        "required_source_keys": expected,
        "required_source_keys_count": required_n,
        "present_source_keys": present_out,
        "matched_source_keys": matched[:200],
        "matched_by_required_source_key": matched_by_required,
        "missing_source_keys": missing,
        "matched_source_keys_count": matched_n,
        "missing_source_keys_count": missing_n,
        "coverage_ratio": round(coverage_ratio, 6),
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
