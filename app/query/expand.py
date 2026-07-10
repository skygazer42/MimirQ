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

        vals: list[Any]
        if isinstance(v, str):
            vals = [v]
        elif isinstance(v, list):
            vals = v
        else:
            continue

        cleaned: list[str] = []
        for item in vals:
            s = str(item or "").strip()
            if not s:
                continue
            # Avoid trivial self-aliasing.
            if s == key:
                continue
            cleaned.append(s)

        if not cleaned:
            continue

        # Stable de-dup (case-insensitive for ASCII).
        seen: set[str] = set()
        unique: list[str] = []
        for s in cleaned:
            sig = s.casefold() if s.isascii() else s
            if sig in seen:
                continue
            seen.add(sig)
            unique.append(s)

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

        per_rule = 0
        for tgt in targets:
            if len(expansions) >= max_expansions_total:
                break
            if per_rule >= max_expansions_per_rule:
                break
            if not tgt:
                continue

            v = _replace(base, key, tgt).strip()
            if not v or v == base:
                continue
            if max_query_chars and len(v) > int(max_query_chars):
                v = v[: int(max_query_chars)] + "..."

            sig = v.casefold() if v.isascii() else v
            if sig in seen:
                continue
            seen.add(sig)

            expansions.append(
                {
                    "expanded_text": v,
                    "source_rule_id": f"dict:{key}",
                    # Weight is intentionally simple today; callers can re-weight later.
                    "weight": 1.0,
                    "src": key,
                    "tgt": tgt,
                }
            )
            per_rule += 1

    return expansions, {
        "enabled": True,
        "used": bool(expansions),
        "generated": len(expansions),
        "rules_total": len(rules_in),
        "max_expansions_total": max_expansions_total,
        "max_expansions_per_rule": max_expansions_per_rule,
        "base_query_chars": len(base),
    }


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

        if not line.startswith((" ", "\t")) and stripped.endswith(":"):
            key = stripped[:-1].strip().strip('"').strip("'")
            current_key = key if key else None
            if current_key and current_key not in parsed:
                parsed[current_key] = []
            continue

        if stripped.startswith("-"):
            if not current_key:
                continue
            val = stripped[1:].strip()
            if not val:
                continue
            if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                if len(val) >= 2:
                    val = val[1:-1]
            parsed.setdefault(current_key, []).append(val)

    return coerce_expansion_rules(parsed)
