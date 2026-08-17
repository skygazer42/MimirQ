"""
Controlled, auditable query expansion utilities.

This module is intentionally deterministic and bounded:
- At most one rule application per expanded query (no combinatorial explosions).
- Stable de-duplication (ASCII case-insensitive).
- Expansion provenance is included with each generated variant.
"""


import re
from pathlib import Path
from typing import Any


def _rule_values(raw: Any) -> list[Any] | None:
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list):
        return raw
    return None


def _unique_rule_values(key: str, raw: Any) -> list[str]:
    values = _rule_values(raw)
    if values is None:
        return []
    seen: set[str] = set()
    unique: list[str] = []
    for item in values:
        value = str(item or "").strip()
        if not value or value == key:
            continue
        signature = value.casefold() if value.isascii() else value
        if signature in seen:
            continue
        seen.add(signature)
        unique.append(value)
    return unique


def coerce_expansion_rules(raw: Any) -> dict[str, list[str]]:
    """
    Coerce a user/dataset-provided expansion dictionary into a normalized mapping.

    Expected shape:
      {
        "SLO": ["service level objective", "service-level objective"],
        "SSO": ["single sign-on", "single sign on"],
      }
    """
    if not isinstance(raw, dict):
        return {}

    out: dict[str, list[str]] = {}
    for k, v in raw.items():
        key = str(k or "").strip()
        if not key:
            continue
        unique = _unique_rule_values(key, v)
        if unique:
            out[key] = unique
    return out


_WORD_EDGE = r"(?<![A-Za-z0-9_]){term}(?![A-Za-z0-9_])"


def _term_pattern(term: str) -> re.Pattern[str]:
    # For ASCII terms, apply case-insensitive match and avoid replacing substrings inside identifiers.
    return re.compile(_WORD_EDGE.format(term=re.escape(term)), flags=re.IGNORECASE)


def _contains(query: str, term: str) -> bool:
    if not query or not term:
        return False
    if term.isascii():
        return bool(_term_pattern(term).search(query))
    return term in query


def _replace(query: str, term: str, replacement: str) -> str:
    if not query or not term:
        return query
    if term.isascii():
        return _term_pattern(term).sub(replacement, query)
    return query.replace(term, replacement)


def _bounded_expansion_text(
    base: str,
    source: str,
    target: str,
    *,
    max_query_chars: int,
) -> str:
    expanded = _replace(base, source, target).strip()
    if max_query_chars and len(expanded) > int(max_query_chars):
        return expanded[: int(max_query_chars)] + "..."
    return expanded


def _append_rule_expansions(
    *,
    expansions: list[dict[str, Any]],
    seen: set[str],
    base: str,
    source: str,
    targets: list[str],
    max_expansions_total: int,
    max_expansions_per_rule: int,
    max_query_chars: int,
) -> None:
    per_rule = 0
    for target in targets:
        if len(expansions) >= max_expansions_total or per_rule >= max_expansions_per_rule:
            break
        if not target:
            continue
        expanded = _bounded_expansion_text(
            base,
            source,
            target,
            max_query_chars=max_query_chars,
        )
        if not expanded or expanded == base:
            continue
        signature = expanded.casefold() if expanded.isascii() else expanded
        if signature in seen:
            continue
        seen.add(signature)
        expansions.append(
            {
                "expanded_text": expanded,
                "source_rule_id": f"dict:{source}",
                "weight": 1.0,
                "src": source,
                "tgt": target,
            }
        )
        per_rule += 1


def generate_dictionary_expansions(
    *,
    query: str,
    rules: dict[str, list[str]] | None,
    max_expansions_total: int = 5,
    max_expansions_per_rule: int = 2,
    max_query_chars: int = 400,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Generate query variants by applying deterministic dictionary rules.

    Returns:
      - expansions: list[dict] each containing {expanded_text, source_rule_id, weight, ...}
      - meta: small dict for traces/metrics
    """
    base = (query or "").strip()
    if not base:
        return [], {"enabled": False, "used": False, "reason": "empty_query"}

    max_expansions_total = max(0, int(max_expansions_total or 0))
    max_expansions_per_rule = max(0, int(max_expansions_per_rule or 0))
    if max_expansions_total <= 0 or max_expansions_per_rule <= 0:
        return [], {"enabled": False, "used": False, "reason": "disabled"}

    rules_in = coerce_expansion_rules(rules)
    if not rules_in:
        return [], {"enabled": False, "used": False, "reason": "no_rules"}

    expansions: list[dict[str, Any]] = []
    seen: set[str] = set()

    for key, targets in rules_in.items():
        if len(expansions) >= max_expansions_total:
            break
        if not _contains(base, key):
            continue
        _append_rule_expansions(
            expansions=expansions,
            seen=seen,
            base=base,
            source=key,
            targets=targets,
            max_expansions_total=max_expansions_total,
            max_expansions_per_rule=max_expansions_per_rule,
            max_query_chars=max_query_chars,
        )

    return expansions, {
        "enabled": True,
        "used": bool(expansions),
        "generated": len(expansions),
        "rules_total": len(rules_in),
        "max_expansions_total": max_expansions_total,
        "max_expansions_per_rule": max_expansions_per_rule,
        "base_query_chars": len(base),
    }


def _dictionary_heading(line: str, stripped: str) -> str | None:
    if line.startswith((" ", "\t")) or not stripped.endswith(":"):
        return None
    return stripped[:-1].strip().strip('"').strip("'")


def _dictionary_list_value(stripped: str) -> str | None:
    if not stripped.startswith("-"):
        return None
    value = stripped[1:].strip()
    if not value:
        return None
    quoted = (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    )
    if quoted and len(value) >= 2:
        return value[1:-1]
    return value


def load_base_dictionary_rules() -> dict[str, list[str]]:
    """
    Load the bundled dictionary rules from `app/query/dictionaries/base.yaml`.

    We intentionally use a tiny YAML subset parser to avoid adding a YAML dependency.
    Supported subset:
      KEY:
        - value
        - value2
    """
    path = Path(__file__).resolve().parent / "dictionaries" / "base.yaml"
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}
    parsed: dict[str, list[str]] = {}
    current_key: str | None = None
    for ln in (raw or "").splitlines():
        line = ln.rstrip("\r\n")
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        heading = _dictionary_heading(line, stripped)
        if heading is not None:
            current_key = heading if heading else None
            if current_key and current_key not in parsed:
                parsed[current_key] = []
            continue
        value = _dictionary_list_value(stripped)
        if value is not None and current_key:
            parsed.setdefault(current_key, []).append(value)

    return coerce_expansion_rules(parsed)
