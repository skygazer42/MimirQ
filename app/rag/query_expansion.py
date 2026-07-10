"""
Query expansion helpers (retrieval-only).

Goal: reduce false negatives (missed recall) by generating additional query variants
in a controlled, auditable way (no surprise Cartesian products).
"""


import re
from typing import Any


def coerce_query_aliases(raw: Any) -> dict[str, list[str]]:
    """
    Coerce a dataset/request-provided alias dictionary into a normalized mapping.

    Expected shape:
      {
        "单点登录": ["SSO", "Single Sign-On"],
        "LLM": ["large language model"],
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


def generate_alias_queries(
    *,
    query: str,
    aliases: dict[str, list[str]] | None,
    max_queries: int = 5,
    max_rules: int = 200,
    max_query_chars: int = 400,
) -> tuple[list[str], dict[str, Any]]:
    """
    Generate query variants by applying dataset-scoped alias rules.

    Design notes:
    - One rule application per generated query (no combinatorial explosions).
    - Case-insensitive matching for ASCII rules, exact for non-ASCII.
    - Returns both the variants and a small meta payload for traces/metrics.
    """
    base = (query or "").strip()
    if not base:
        return [], {"enabled": False, "used": False, "reason": "empty_query"}

    max_queries = max(0, int(max_queries or 0))
    if max_queries <= 0:
        return [], {"enabled": False, "used": False, "reason": "max_queries_le_0"}

    rules_in = coerce_query_aliases(aliases)
    if not rules_in:
        return [], {"enabled": False, "used": False, "reason": "no_aliases"}

    base_fold = base.casefold()

    def _contains(src: str) -> bool:
        if not src:
            return False
        if src.isascii():
            return src.casefold() in base_fold
        return src in base

    def _replace(src: str, tgt: str) -> str:
        if not src:
            return base
        if src.isascii():
            # Case-insensitive replacement for ASCII terms.
            return re.sub(re.escape(src), tgt, base, flags=re.IGNORECASE)
        return base.replace(src, tgt)

    variants: list[str] = []
    seen: set[str] = set()
    applied: list[dict[str, str]] = []

    # Build symmetric rule pairs: key <-> alias
    pairs: list[tuple[str, str]] = []
    for k, vs in rules_in.items():
        for a in vs:
            if not a:
                continue
            if a == k:
                continue
            pairs.append((k, a))
            pairs.append((a, k))

    # Stable de-dup of pairs.
    uniq_pairs: list[tuple[str, str]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for src, tgt in pairs:
        key = (src.casefold() if src.isascii() else src, tgt.casefold() if tgt.isascii() else tgt)
        if key in seen_pairs:
            continue
        seen_pairs.add(key)
        uniq_pairs.append((src, tgt))

    for src, tgt in uniq_pairs[: max(0, int(max_rules or 0))]:
        if len(variants) >= max_queries:
            break
        if not _contains(src):
            continue
        v = _replace(src, tgt).strip()
        if not v or v == base:
            continue
        if max_query_chars and len(v) > int(max_query_chars):
            v = v[: int(max_query_chars)] + "..."
        sig = v.casefold() if v.isascii() else v
        if sig in seen:
            continue
        seen.add(sig)
        variants.append(v)
        applied.append({"src": src, "tgt": tgt})

    return variants, {
        "enabled": True,
        "used": bool(variants),
        "base_query_chars": len(base),
        "max_queries": max_queries,
        "rules_total": sum(len(v) for v in rules_in.values()),
        "rules_considered": min(len(uniq_pairs), max(0, int(max_rules or 0))),
        "generated": len(variants),
        "applied": applied[:8],
        "queries": variants[:8],
    }

