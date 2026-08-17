"""
Query expansion helpers (retrieval-only).

Goal: reduce false negatives (missed recall) by generating additional query variants
in a controlled, auditable way (no surprise Cartesian products).
"""


import re
from typing import Any


def _alias_values(raw: Any) -> list[Any] | None:
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list):
        return raw
    return None


def _unique_alias_values(key: str, raw: Any) -> list[str]:
    values = _alias_values(raw)
    if values is None:
        return []
    seen: set[str] = set()
    unique: list[str] = []
    for item in values:
        alias = str(item or "").strip()
        if not alias or alias == key:
            continue
        signature = alias.casefold() if alias.isascii() else alias
        if signature in seen:
            continue
        seen.add(signature)
        unique.append(alias)
    return unique


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
        unique = _unique_alias_values(key, v)
        if unique:
            out[key] = unique
    return out


def _query_contains_alias(base: str, base_fold: str, source: str) -> bool:
    if not source:
        return False
    if source.isascii():
        return source.casefold() in base_fold
    return source in base


def _replace_alias(base: str, source: str, target: str) -> str:
    if not source:
        return base
    if source.isascii():
        return re.sub(re.escape(source), target, base, flags=re.IGNORECASE)
    return base.replace(source, target)


def _symmetric_alias_pairs(rules: dict[str, list[str]]) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for key, aliases in rules.items():
        for alias in aliases:
            if not alias or alias == key:
                continue
            pairs.append((key, alias))
            pairs.append((alias, key))
    seen: set[tuple[str, str]] = set()
    unique: list[tuple[str, str]] = []
    for source, target in pairs:
        signature = (
            source.casefold() if source.isascii() else source,
            target.casefold() if target.isascii() else target,
        )
        if signature in seen:
            continue
        seen.add(signature)
        unique.append((source, target))
    return unique


def _bounded_alias_variant(base: str, source: str, target: str, *, max_query_chars: int) -> str:
    variant = _replace_alias(base, source, target).strip()
    if max_query_chars and len(variant) > int(max_query_chars):
        return variant[: int(max_query_chars)] + "..."
    return variant


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
    variants: list[str] = []
    seen: set[str] = set()
    applied: list[dict[str, str]] = []
    uniq_pairs = _symmetric_alias_pairs(rules_in)
    for src, tgt in uniq_pairs[: max(0, int(max_rules or 0))]:
        if len(variants) >= max_queries:
            break
        if not _query_contains_alias(base, base_fold, src):
            continue
        v = _bounded_alias_variant(base, src, tgt, max_query_chars=max_query_chars)
        if not v or v == base:
            continue
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
